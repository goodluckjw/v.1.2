v1.2#
#gemoni가 수정함 

import os
import re
import unicodedata
from collections import defaultdict
from urllib.parse import quote

import requests
import xml.etree.ElementTree as ET

OC = os.getenv("OC", "chetera")
BASE = "http://www.law.go.kr"


def normalize_middle_dot(text):
    if text is None:
        return ""
    return str(text).replace("·", "ㆍ").replace("#", "ㆍ")


def normalize_brackets(text):
    if text is None:
        return ""
    return str(text).replace("{", "「").replace("}", "」")


def normalize_input_text(text):
    if text is None:
        return ""
    return normalize_brackets(normalize_middle_dot(str(text))).strip()


def canonicalize_display_text(text):
    text = normalize_input_text(text)
    if not text:
        return ""
    text = re.sub(r"\s*「\s*", "「", text)
    text = re.sub(r"\s*」\s*", "」", text)
    text = re.sub(r"\s*ㆍ\s*", "ㆍ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def normalize_for_compare(text, ignore_space=True):
    text = canonicalize_display_text(text)
    if ignore_space:
        return re.sub(r"\s+", "", text)
    return text


def contains_query(text, query, ignore_space=True):
    text_norm = normalize_for_compare(text, ignore_space=ignore_space)
    query_norm = normalize_for_compare(query, ignore_space=ignore_space)
    return bool(query_norm) and query_norm in text_norm


def build_space_flexible_pattern(query):
    query = canonicalize_display_text(query)
    if not query:
        return None
    parts = [re.escape(p) for p in re.split(r"\s+", query.strip()) if p]
    if not parts:
        return None
    return re.compile(r"\s*".join(parts), re.IGNORECASE)


def highlight(text, query, ignore_space=True):
    if not text:
        return ""
    if not query:
        return text
    if ignore_space:
        pattern = build_space_flexible_pattern(query)
        if pattern:
            return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", text)
    pattern = re.compile(re.escape(canonicalize_display_text(query)), re.IGNORECASE)
    return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", text)


def get_law_list_from_api(query, search_type="2"):
    normalized_query = normalize_input_text(query)
    clean_query = re.sub(r'[^가-힣A-Za-z0-9\s]', ' ', normalized_query)
    words = clean_query.split()
    stopwords = {"관한", "법률", "따른", "에따른", "의한", "대하여", "위한", "관하여"}
    filtered_words = [w for w in words if w not in stopwords]
    target_words = filtered_words if filtered_words else words
    api_keyword = max(target_words, key=len) if target_words else normalized_query
    
    encoded_query = quote(api_keyword)
    page = 1
    laws = []
    seen = set()
    while True:
        url = (
            f"{BASE}/DRF/lawSearch.do"
            f"?OC={OC}&target=law&type=XML&display=100&page={page}"
            f"&search={search_type}&knd=A0002&query={encoded_query}"
        )
        try:
            res = requests.get(url, timeout=15)
            res.encoding = "utf-8"
            if res.status_code != 200:
                break
            root = ET.fromstring(res.content)
            page_laws = root.findall("law")
            if not page_laws:
                break
            for law in page_laws:
                name = (law.findtext("법령명한글", "") or "").strip()
                mst = (law.findtext("법령일련번호", "") or "").strip()
                if mst and mst not in seen:
                    seen.add(mst)
                    laws.append({"법령명": name, "MST": mst})
            if len(page_laws) < 100:
                break
            page += 1
        except Exception as e:
            print(f"법률 검색 중 오류 발생: {e}")
            break
    return laws


def get_law_text_by_mst(mst):
    if not mst:
        return None
    url = f"{BASE}/DRF/lawService.do?OC={OC}&target=law&type=XML&MST={quote(str(mst))}"
    try:
        res = requests.get(url, timeout=20)
        if res.status_code != 200:
            return None
        res.encoding = "utf-8"
        return res.text
    except Exception as e:
        print(f"법령 본문 조회 오류(MST={mst}): {e}")
        return None


def normalize_number(text):
    try:
        return str(int(unicodedata.numeric(text)))
    except Exception:
        return text


def make_article_number(jo_num, jo_sub_num):
    return f"제{jo_num}조의{jo_sub_num}" if jo_sub_num and jo_sub_num != "0" else f"제{jo_num}조"


def _get_last_korean_char(word):
    for char in reversed(word):
        if "가" <= char <= "힣":
            return char
    return None


def has_batchim(word):
    char = _get_last_korean_char(word)
    if char:
        return (ord(char) - 0xAC00) % 28 != 0
    return False


def has_rieul_batchim(word):
    char = _get_last_korean_char(word)
    if char:
        return (ord(char) - 0xAC00) % 28 == 8
    return False


def extract_article_num(loc):
    m = re.search(r"제(\d+)조(?:의(\d+))?", loc)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else 0)


def preprocess_search_term(search_term):
    normalized = canonicalize_display_text(search_term)
    if normalized.startswith('"') and normalized.endswith('"') and len(normalized) >= 2:
        return canonicalize_display_text(normalized[1:-1]), True
    if re.search(r"\s+", normalized):
        return normalized, True
    return normalized, False


def apply_josa_rule(A, B, josa):
    A_has_b = has_batchim(A)
    B_has_b = has_batchim(B)
    B_has_r = has_rieul_batchim(B)

    # 0. 조사가 붙지 않은 경우 (의, 에 등 포함)
    if not josa:
        if not A_has_b:
            if not B_has_b: return f'"{A}"를 "{B}"로 한다.'
            if B_has_r: return f'"{A}"를 "{B}"로 한다.'
            return f'"{A}"를 "{B}"으로 한다.'
        else:
            if not B_has_b: return f'"{A}"을 "{B}"로 한다.'
            if B_has_r: return f'"{A}"을 "{B}"로 한다.'
            return f'"{A}"을 "{B}"으로 한다.'

    # 1. 을
    if josa == "을":
        if B_has_b:
            if B_has_r: return f'"{A}"을 "{B}"로 한다.'
            return f'"{A}"을 "{B}"으로 한다.'
        return f'"{A}을"을 "{B}를"로 한다.'

    # 2. 를
    if josa == "를":
        if B_has_b: return f'"{A}를"을 "{B}을"로 한다.'
        return f'"{A}"를 "{B}"로 한다.'

    # 3. 과
    if josa == "과":
        if B_has_b:
            if B_has_r: return f'"{A}"을 "{B}"로 한다.'
            return f'"{A}"을 "{B}"으로 한다.'
        return f'"{A}과"를 "{B}와"로 한다.'

    # 4. 와
    if josa == "와":
        if B_has_b: return f'"{A}와"를 "{B}과"로 한다.'
        return f'"{A}"를 "{B}"로 한다.'

    # 5. 이
    if josa == "이":
        if B_has_b:
            if B_has_r: return f'"{A}"을 "{B}"로 한다.'
            return f'"{A}"을 "{B}"으로 한다.'
        return f'"{A}이"를 "{B}가"로 한다.'

    # 6. 가
    if josa == "가":
        if B_has_b: return f'"{A}가"를 "{B}이"로 한다.'
        return f'"{A}"를 "{B}"로 한다.'

    # 7. 이나 (오류 교정 적용: 이나 유지)
    if josa == "이나":
        if B_has_b: return f'"{A}이나"를 "{B}이나"로 한다.'
        return f'"{A}이나"를 "{B}나"로 한다.'

    # 8. 나 (오류 교정 적용: 나 유지)
    if josa == "나":
        if B_has_b: return f'"{A}나"를 "{B}이나"로 한다.'
        return f'"{A}나"를 "{B}나"로 한다.'

    # 9. 으로
    if josa == "으로":
        if B_has_b:
            if B_has_r: return f'"{A}으로"를 "{B}로"로 한다.'
            return f'"{A}"을 "{B}"으로 한다.'
        return f'"{A}으로"를 "{B}로"로 한다.'

    # 10. 로
    if josa == "로":
        if A_has_b:
            if B_has_b:
                if B_has_r: return f'"{A}"을 "{B}"로 한다.'
                return f'"{A}로"를 "{B}으로"로 한다.'
            return f'"{A}"을 "{B}"로 한다.'
        else:
            if B_has_b:
                if B_has_r: return f'"{A}"를 "{B}"로 한다.'
                return f'"{A}로"를 "{B}으로"로 한다.'
            return f'"{A}"를 "{B}"로 한다.'

    # 11. 는
    if josa == "는":
        if B_has_b: return f'"{A}는"을 "{B}은"으로 한다.'
        return f'"{A}"를 "{B}"로 한다.'

    # 12. 은
    if josa == "은":
        if B_has_b:
            if B_has_r: return f'"{A}"을 "{B}"로 한다.'
            return f'"{A}"을 "{B}"으로 한다.'
        return f'"{A}은"을 "{B}는"으로 한다.'

    # 13. 란
    if josa == "란":
        if B_has_b: return f'"{A}란"을 "{B}이란"으로 한다.'
        return f'"{A}"를 "{B}"로 한다.'

    # 14. 이란
    if josa == "이란":
        if B_has_b:
            if B_has_r: return f'"{A}"을 "{B}"로 한다.'
            return f'"{A}"을 "{B}"으로 한다.'
        return f'"{A}이란"을 "{B}란"으로 한다.'

    return f'"{A}"을 "{B}"로 한다.'


def format_location(loc):
    loc = re.sub(r"제(?=항)", "", loc)
    loc = re.sub(r"(\d+)\.호", r"\1호", loc)
    loc = re.sub(r"([가-힣])\.목", r"\1목", loc)
    return loc


def parse_location(loc):
    article_match = re.search(r"제(\d+)조(?:의(\d+))?", loc)
    article_num = int(article_match.group(1)) if article_match else 0
    article_sub = int(article_match.group(2)) if article_match and article_match.group(2) else 0
    clause_match = re.search(r"제(\d+)항", loc)
    clause_num = int(clause_match.group(1)) if clause_match else 0
    item_match = re.search(r"제(\d+)호(?:의(\d+))?", loc)
    item_num = int(item_match.group(1)) if item_match else 0
    item_sub = int(item_match.group(2)) if item_match and item_match.group(2) else 0
    subitem_match = re.search(r"([가-힣])목", loc)
    subitem_num = ord(subitem_match.group(1)) - ord("가") + 1 if subitem_match else 0
    is_title = 1 if "제목" in loc else 0
    outside_parts = 1 if "외의 부분" in loc else 0
    return (article_num, article_sub, clause_num, item_num, item_sub, outside_parts, subitem_num, is_title)


def group_locations(loc_list):
    if not loc_list:
        return ""
    formatted_locs = [format_location(loc) for loc in loc_list]
    sorted_locs = sorted(formatted_locs, key=parse_location)
    article_groups = {}
    for loc in sorted_locs:
        article_match = re.match(r"(제\d+조(?:의\d+)?)", loc)
        if not article_match:
            continue
        article_num = article_match.group(1)
        rest_part = loc[len(article_num):]
        appendix_match = re.search(r"(제\d+호)의(\d+)", rest_part)
        if appendix_match:
            rest_part = rest_part.replace(appendix_match.group(0), f"{appendix_match.group(1)}의{appendix_match.group(2)}")
        clause_part = ""
        clause_match = re.search(r"(제\d+항)", rest_part)
        if clause_match:
            clause_part = clause_match.group(1)
            rest_part = rest_part[rest_part.find(clause_part) + len(clause_part):]
        title_part = ""
        if " 제목" in loc:
            title_part = " 제목 및 본문" if " 제목 및 본문" in loc else " 제목"
            rest_part = rest_part.replace(title_part, "")
        outside_part = ""
        if " 각 목 외의 부분" in loc or " 외의 부분" in loc:
            outside_part = " 각 목 외의 부분"
            rest_part = rest_part.replace(" 각 목 외의 부분", "").replace(" 외의 부분", "")
        item_goal_part = ""
        if "제" in rest_part and ("호" in rest_part or "목" in rest_part):
            appendix_match = re.search(r"(제\d+호)의(\d+)", rest_part)
            if appendix_match:
                item_goal_part = appendix_match.group(0)
            else:
                item_match = re.match(r"제\d+호|[가-힣]목", rest_part.strip())
                if item_match:
                    item_goal_part = rest_part.strip()
        article_groups.setdefault(article_num, []).append((clause_part, title_part, outside_part, item_goal_part))
    result_parts = []
    for article_num, items in sorted(article_groups.items(), key=lambda x: extract_article_num(x[0])):
        clause_groups = {}
        for clause, title, outside, item_goal in items:
            key = (clause, title, outside)
            clause_groups.setdefault(key, [])
            if item_goal:
                clause_groups[key].append(item_goal)
        article_clause_parts = []
        def clause_sort_key(entry):
            clause = entry[0][0]
            m = re.search(r"제(\d+)항", clause)
            return int(m.group(1)) if m else 0
        for (clause, title, outside), item_goals in sorted(clause_groups.items(), key=clause_sort_key):
            loc_str = article_num
            if title:
                loc_str += title
            if clause:
                loc_str += clause
            if outside:
                loc_str += outside
            if item_goals:
                sorted_items = sorted(item_goals, key=lambda x: parse_location(f"{article_num}{clause}{x}"))
                unique_items = []
                for item in sorted_items:
                    if item not in unique_items:
                        unique_items.append(item)
                if unique_items:
                    loc_str += "ㆍ".join(item if item.startswith("제") else f"제{item}" for item in unique_items)
            article_clause_parts.append(loc_str)
        result_parts.extend(article_clause_parts)
    if not result_parts:
        return ""
    if len(result_parts) == 1:
        return result_parts[0]
    return ", ".join(result_parts[:-1]) + f" 및 {result_parts[-1]}"


def add_gaggag_if_needed(rule, locs):
    if len(locs) > 1 and "각각" not in rule:
        m = re.match(r'^(".*?")(을|를|과|와|이|가|는|은|이나|나|으로|로|란|이란)\s+(".*?")(으로|로)( 한다\.)$', rule)
        if m:
            return f"{m.group(1)}{m.group(2)} 각각 {m.group(3)}{m.group(4)}{m.group(5)}"
        m2 = re.match(r'^(".*?")\s+(".*?")(으로|로)( 한다\.)$', rule)
        if m2:
             return f"{m2.group(1)} 각각 {m2.group(2)}{m2.group(3)}{m2.group(4)}"
    return rule


def run_amendment_logic(find_word, replace_word, exclude_laws=None, ignore_space=True):
    amendment_results = []
    skipped_laws = []
    if exclude_laws is None:
        exclude_laws = []
    normalized_exclude_laws = [normalize_for_compare(law, ignore_space=True) for law in exclude_laws if str(law).strip()]
    normalized_find_word = normalize_input_text(find_word)
    normalized_replace_word = normalize_input_text(replace_word)
    processed_find_word, _ = preprocess_search_term(normalized_find_word)
    processed_replace_word = canonicalize_display_text(normalized_replace_word)
    
    laws = get_law_list_from_api(processed_find_word, search_type="2")
    output_count = 0
    
    for idx, law in enumerate(laws):
        law_name = law["법령명"]
        normalized_law_name = normalize_for_compare(law_name, ignore_space=True)
        if normalized_law_name in normalized_exclude_laws:
            skipped_laws.append(f"{law_name}: 사용자 지정 배제 법률")
            continue
            
        mst = law["MST"]
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            continue
            
        try:
            tree = ET.fromstring(xml_data)
        except ET.ParseError as e:
            continue
            
        articles = tree.findall(".//조문단위")
        if not articles:
            continue
            
        chunk_map = defaultdict(list)
        found_in_buchik = False
        
        def extract_matches_from_text(target_text, location):
            pattern = build_space_flexible_pattern(processed_find_word) if ignore_space else re.compile(re.escape(processed_find_word))
            if not pattern:
                return
                
            for m in pattern.finditer(str(target_text)):
                start = m.start()
                end = m.end()
                
                # 스마트 덩어리 확장 (한글, 영문, 숫자만 허용. 기호 만나면 즉시 중단)
                while start > 0 and re.match(r'[가-힣A-Za-z0-9]', target_text[start-1]):
                    start -= 1
                while end < len(target_text) and re.match(r'[가-힣A-Za-z0-9]', target_text[end]):
                    end += 1
                    
                raw_chunk = target_text[start:end]
                
                # 지정된 14개 조사 리스트 (분리 대상)
                josa_list = ["이란", "이나", "으로", "을", "를", "과", "와", "이", "가", "나", "로", "는", "은", "란"]
                found_josa = None
                A_base = raw_chunk
                
                for j in josa_list:
                    if raw_chunk.endswith(j):
                        temp_base = raw_chunk[:-len(j)]
                        if pattern.search(temp_base):
                            found_josa = j
                            A_base = temp_base
                            break
                            
                A_canon = canonicalize_display_text(A_base)
                B_canon = canonicalize_display_text(pattern.sub(processed_replace_word, A_canon, count=1))
                
                chunk_map[(A_canon, B_canon, found_josa)].append(location)

        for article in articles:
            jo_num = (article.findtext("조문번호", "") or "").strip()
            jo_sub_num = (article.findtext("조문가지번호", "") or "").strip()
            article_id = make_article_number(jo_num, jo_sub_num)
            jo_name = (article.findtext("조문명", "") or "").strip()
            is_buchik = "부칙" in jo_name
            jo_title = article.findtext("조문제목", "") or ""
            jo_body = article.findtext("조문내용", "") or ""
            
            title_hit = contains_query(jo_title, processed_find_word, ignore_space=ignore_space)
            body_hit = contains_query(jo_body, processed_find_word, ignore_space=ignore_space)
            
            if title_hit or body_hit:
                if is_buchik:
                    found_in_buchik = True
                else:
                    if title_hit: extract_matches_from_text(jo_title, f"{article_id} 제목")
                    if body_hit: extract_matches_from_text(jo_body, f"{article_id}")
                        
            for hang in article.findall("항"):
                hang_num = normalize_number((hang.findtext("항번호", "") or "").strip())
                hang_part = f"제{hang_num}항" if hang_num else ""
                has_outer_mok = any(ho.attrib.get("구분") == "각목외의부분" for ho in hang.findall("호"))
                hang_body = hang.findtext("항내용", "") or ""
                
                if contains_query(hang_body, processed_find_word, ignore_space=ignore_space):
                    if is_buchik:
                        found_in_buchik = True
                    else:
                        loc = f"{article_id}{hang_part}{' 각 목 외의 부분' if has_outer_mok else ''}"
                        extract_matches_from_text(hang_body, loc)
                        
                for ho in hang.findall("호"):
                    ho_num = ho.findtext("호번호")
                    ho_sub_num = ho.findtext("호가지번호") if ho.find("호가지번호") is not None else None
                    ho_body = ho.findtext("호내용", "") or ""
                    
                    if contains_query(ho_body, processed_find_word, ignore_space=ignore_space):
                        if is_buchik:
                            found_in_buchik = True
                        else:
                            ho_label = f"제{ho_num}호" + (f"의{ho_sub_num}" if ho_sub_num else "")
                            loc = f"{article_id}{hang_part}{ho_label}"
                            extract_matches_from_text(ho_body, loc)
                            
                    for mok in ho.findall("목"):
                        mok_num = mok.findtext("목번호")
                        for mok_body_node in mok.findall("목내용"):
                            if not mok_body_node.text:
                                continue
                            mok_text = mok_body_node.text
                            if contains_query(mok_text, processed_find_word, ignore_space=ignore_space):
                                if is_buchik:
                                    found_in_buchik = True
                                else:
                                    ho_label = f"제{ho_num}호" + (f"의{ho_sub_num}" if ho_sub_num else "")
                                    loc = f"{article_id}{hang_part}{ho_label}{mok_num}목"
                                    for line in mok_text.splitlines():
                                        if contains_query(line, processed_
