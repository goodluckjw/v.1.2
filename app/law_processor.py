#v1.2
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


# [핵심] 사용자의 14가지 규칙 완벽 적용 함수
def apply_josa_rule(A, B, josa):
    A_batchim = has_batchim(A)
    B_batchim = has_batchim(B)
    B_rieul = has_rieul_batchim(B)

    if not josa:  # 0. 조사가 붙지 않은 경우
        if not A_batchim:
            if not B_batchim: return f'"{A}"를 "{B}"로 한다.'
            else:
                if B_rieul: return f'"{A}"를 "{B}"로 한다.'
                else: return f'"{A}"를 "{B}"으로 한다.'
        else:
            if not B_batchim: return f'"{A}"을 "{B}"로 한다.'
            else:
                if B_rieul: return f'"{A}"을 "{B}"로 한다.'
                else: return f'"{A}"을 "{B}"으로 한다.'

    if josa == "을":  # 1
        if B_batchim:
            if B_rieul: return f'"{A}"을 "{B}"로 한다.'
            else: return f'"{A}"을 "{B}"으로 한다.'
        else: return f'"{A}을"을 "{B}를"로 한다.'

    if josa == "를":  # 2
        if B_batchim: return f'"{A}를"을 "{B}을"로 한다.'
        else: return f'"{A}"를 "{B}"로 한다.'

    if josa == "과":  # 3
        if B_batchim:
            if B_rieul: return f'"{A}"을 "{B}"로 한다.'
            else: return f'"{A}"을 "{B}"으로 한다.'
        else: return f'"{A}과"를 "{B}와"로 한다.'

    if josa == "와":  # 4
        if B_batchim: return f'"{A}와"를 "{B}과"로 한다.'
        else: return f'"{A}"를 "{B}"로 한다.'

    if josa == "이":  # 5
        if B_batchim:
            if B_rieul: return f'"{A}"을 "{B}"로 한다.'
            else: return f'"{A}"을 "{B}"으로 한다.'
        else: return f'"{A}이"를 "{B}가"로 한다.'

    if josa == "가":  # 6
        if B_batchim: return f'"{A}가"를 "{B}이"로 한다.'
        else: return f'"{A}"를 "{B}"로 한다.'

    if josa == "이나":  # 7
        if B_batchim:
            if B_rieul: return f'"{A}"을 "{B}"로 한다.'
            else: return f'"{A}"을 "{B}"으로 한다.'
        else: return f'"{A}이나"를 "{B}나"로 한다.'

    if josa == "나":  # 8
        if B_batchim: return f'"{A}나"를 "{B}이나"로 한다.'
        else: return f'"{A}"를 "{B}"로 한다.'

    if josa == "으로":  # 9
        if B_batchim:
            if B_rieul: return f'"{A}으로"를 "{B}로"로 한다.'
            else: return f'"{A}"을 "{B}"으로 한다.'
        else: return f'"{A}으로"를 "{B}로"로 한다.'

    if josa == "로":  # 10
        if A_batchim:
            if B_batchim:
                if B_rieul: return f'"{A}"을 "{B}"로 한다.'
                else: return f'"{A}로"를 "{B}으로"로 한다.'
            else: return f'"{A}"을 "{B}"로 한다.'
        else:
            if B_batchim:
                if B_rieul: return f'"{A}"를 "{B}"로 한다.'
                else: return f'"{A}로"를 "{B}으로"로 한다.'
            else: return f'"{A}"를 "{B}"로 한다.'

    if josa == "는":  # 11
        if B_batchim: return f'"{A}는"을 "{B}은"으로 한다.'
        else: return f'"{A}"를 "{B}"로 한다.'

    if josa == "은":  # 12
        if B_batchim:
            if B_rieul: return f'"{A}"을 "{B}"로 한다.'
            else: return f'"{A}"을 "{B}"으로 한다.'
        else: return f'"{A}은"을 "{B}는"으로 한다.'

    if josa == "란":  # 13
        if B_batchim: return f'"{A}란"을 "{B}이란"으로 한다.'
        else: return f'"{A}"를 "{B}"로 한다.'

    if josa == "이란":  # 14
        if B_batchim:
            if B_rieul: return f'"{A}"을 "{B}"로 한다.'
            else: return f'"{A}"을 "{B}"으로 한다.'
        else: return f'"{A}이란"을 "{B}란"으로 한다.'
        
    return f'"{A}"를 "{B}"로 한다.'


# [핵심] 조문 단위로 묶어서 예쁜 포맷으로 병합하는 함수
def build_article_amendment(article, matches):
    rule_to_details = defaultdict(list)
    for detail, base, replaced, josa in matches:
        rule_text = apply_josa_rule(base, replaced, josa)
        if detail not in rule_to_details[rule_text]:
            rule_to_details[rule_text].append(detail)
            
    def detail_sort_key(d):
        if d == "제목": return 0
        if d == "본문" or d == "": return 1
        hang = int(re.search(r'제(\d+)항', d).group(1)) if re.search(r'제(\d+)항', d) else 0
        ho = int(re.search(r'제(\d+)호', d).group(1)) if re.search(r'제(\d+)호', d) else 0
        return (2, hang, ho)

    formatted_phrases = []
    sorted_rule_groups = sorted(rule_to_details.items(), key=lambda x: min([detail_sort_key(d) for d in x[1]]))
    
    total_details = sum(len(v) for v in rule_to_details.values())
    
    for rule_text, details in sorted_rule_groups:
        sorted_details = sorted(details, key=detail_sort_key)
        
        display_details = []
        for d in sorted_details:
            if not d:
                display_details.append("본문" if total_details > 1 else "")
            else:
                display_details.append(d)
                
        display_details = [d for d in display_details if d]
        
        if not display_details:
            detail_str = ""
        elif len(display_details) == 1:
            detail_str = display_details[0]
        else:
            detail_str = ", ".join(display_details[:-1]) + " 및 " + display_details[-1]
            
        if len(display_details) > 1 and "각각" not in rule_text:
            parts = re.match(r'(".*?")(을|를) (".*?")(으로|로) 한다\.?', rule_text)
            if parts:
                rule_text = f'{parts.group(1)}{parts.group(2)} 각각 {parts.group(3)}{parts.group(4)} 한다.'
        
        rule_stripped = rule_text.replace(" 한다.", "")
        
        if detail_str:
            formatted_phrases.append(f"{detail_str} 중 {rule_stripped}")
        else:
            formatted_phrases.append(f"중 {rule_stripped}")
            
    res = f"{article}"
    if formatted_phrases:
        if formatted_phrases[0].startswith("중 "):
            res += f" {formatted_phrases[0]}"
            formatted_phrases = formatted_phrases[1:]
            if formatted_phrases:
                res += ", " + ", ".join(formatted_phrases)
        else:
            res += " " + ", ".join(formatted_phrases)
    
    return res.strip() + " 한다."


def is_allowed_char(c):
    # 특수기호나 문장부호를 만나면 확장을 멈춤 (한글, 영문, 숫자, 가운뎃점만 허용)
    return bool(re.match(r'[가-힣A-Za-z0-9ㆍ]', c))


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
    print(f"총 {len(laws)}개 법률이 검색되었습니다.")
    output_count = 0
    
    for idx, law in enumerate(laws):
        law_name = law["법령명"]
        normalized_law_name = normalize_for_compare(law_name, ignore_space=True)
        if normalized_law_name in normalized_exclude_laws:
            skipped_laws.append(f"{law_name}: 사용자 지정 배제 법률")
            continue
            
        mst = law["MST"]
        print(f"처리 중: {idx + 1}/{len(laws)} - {law_name} (MST: {mst})")
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            skipped_laws.append(f"{law_name}: XML 데이터 없음")
            continue
            
        try:
            tree = ET.fromstring(xml_data)
        except ET.ParseError as e:
            skipped_laws.append(f"{law_name}: XML 파싱 오류 - {str(e)}")
            continue
            
        articles = tree.findall(".//조문단위")
        if not articles:
            skipped_laws.append(f"{law_name}: 조문단위 없음")
            continue
            
        article_chunk_map = defaultdict(list)
        found_in_buchik = False
        
        def extract_matches_from_text(target_text, raw_loc):
            pattern = build_space_flexible_pattern(processed_find_word) if ignore_space else re.compile(re.escape(processed_find_word))
            if not pattern:
                return
                
            for m in pattern.finditer(str(target_text)):
                start = m.start()
                end = m.end()
                
                # [핵심] 똑똑한 경계 인식: 허용된 글자일 때만 덩어리 확장 (괄호, 따옴표 등에서 멈춤)
                while start > 0 and is_allowed_char(target_text[start-1]):
                    start -= 1
                while end < len(target_text) and is_allowed_char(target_text[end]):
                    end += 1
                    
                token = target_text[start:end]
                token_norm = normalize_input_text(token)
                
                # 정확히 14개의 목표 조사만 타겟팅 (길이가 긴 것부터 확인하여 오작동 방지)
                josa_list = ["이란", "으로", "이나", "은", "는", "이", "가", "을", "를", "과", "와", "나", "로", "란"]
                found_josa = None
                base_chunk = token_norm
                
                for j in josa_list:
                    if token_norm.endswith(j):
                        temp_base = token_norm[:-len(j)]
                        # 조사를 떼어내도 원래 검색어가 파괴되지 않는지 확인
                        if pattern.search(temp_base):
                            found_josa = j
                            base_chunk = temp_base
                            break
                            
                base_chunk_canon = canonicalize_display_text(base_chunk)
                replaced = canonicalize_display_text(pattern.sub(processed_replace_word, base_chunk_canon, count=1))
                
                # 위치(loc) 문자열을 조(Article)와 세부위치(Detail)로 분리
                am = re.match(r"(제\d+조(?:의\d+)?)\s*(.*)", raw_loc)
                if am:
                    article_num = am.group(1)
                    detail_part = am.group(2).strip()
                else:
                    article_num = raw_loc
                    detail_part = ""
                    
                article_chunk_map[article_num].append((detail_part, base_chunk_canon, replaced, found_josa))

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
                        loc = f"{article_id} {hang_part}{' 각 목 외의 부분' if has_outer_mok else ''}"
                        extract_matches_from_text(hang_body, loc.strip())
                        
                for ho in hang.findall("호"):
                    ho_num = ho.findtext("호번호")
                    ho_sub_num = ho.findtext("호가지번호") if ho.find("호가지번호") is not None else None
                    ho_body = ho.findtext("호내용", "") or ""
                    
                    if contains_query(ho_body, processed_find_word, ignore_space=ignore_space):
                        if is_buchik:
                            found_in_buchik = True
                        else:
                            ho_label = f"제{ho_num}호" + (f"의{ho_sub_num}" if ho_sub_num else "")
                            loc = f"{article_id} {hang_part}{ho_label}"
                            extract_matches_from_text(ho_body, loc.strip())
                            
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
                                    loc = f"{article_id} {hang_part}{ho_label}{mok_num}목"
                                    for line in mok_text.splitlines():
                                        if contains_query(line, processed_find_word, ignore_space=ignore_space):
                                            extract_matches_from_text(line, loc.strip())
                                            
        if not article_chunk_map:
            if found_in_buchik:
                skipped_laws.append(f"{law_name}: 부칙에서만 검색어 발견")
            continue
            
        consolidated_rules = []
        # 조문(Article) 단위로 그룹화하여 유려하게 병합
        for article_id_key, matches in article_chunk_map.items():
            amendment_line = build_article_amendment(article_id_key, matches)
            consolidated_rules.append(amendment_line)
            
        if consolidated_rules:
            output_count += 1
            prefix = chr(9312 + output_count - 1) if output_count <= 20 else f"({output_count})"
            amendment = f"{prefix} {law_name} 일부를 다음과 같이 개정한다.<br>"
            for rule in consolidated_rules:
                amendment += rule + "<br>"
            amendment_results.append(amendment)
        else:
            skipped_laws.append(f"{law_name}: 결과줄이 생성되지 않음")
            
    if skipped_laws:
        print("---누락된 법률 목록---")
        for law in skipped_laws:
            print(law)
            
    return amendment_results if amendment_results else ["⚠️ 개정 대상 조문이 없습니다."]


def run_search_logic(query, unit="법률", include_title=False, ignore_space=True):
    normalized_query = normalize_input_text(query)
    result_dict = {}
    candidate_laws = get_law_list_from_api(normalized_query, search_type="2")
    if include_title:
        merged = {law["MST"]: law for law in candidate_laws}
        for law in get_law_list_from_api(normalized_query, search_type="1"):
            merged[law["MST"]] = law
        candidate_laws = list(merged.values())
        
    for law in candidate_laws:
        xml_data = get_law_text_by_mst(law["MST"])
        if not xml_data:
            continue
        try:
            tree = ET.fromstring(xml_data)
        except ET.ParseError:
            continue
        law_results = []
        for article in tree.findall(".//조문단위"):
            jo_num = (article.findtext("조문번호", "") or "").strip()
            jo_sub_num = (article.findtext("조문가지번호", "") or "").strip()
            article_id = make_article_number(jo_num, jo_sub_num)
            jo_title = article.findtext("조문제목", "") or ""
            jo_body = article.findtext("조문내용", "") or ""
            hangs = article.findall("항")
            output_chunks = []
            
            title_hit = include_title and contains_query(jo_title, normalized_query, ignore_space=ignore_space)
            body_hit = contains_query(jo_body, normalized_query, ignore_space=ignore_space)
            first_hang_attached = False
            
            if title_hit:
                output_chunks.append(f"<b>[제목]</b> {highlight(jo_title, normalized_query, ignore_space=ignore_space)}")
            if body_hit:
                output_chunks.append(highlight(jo_body, normalized_query, ignore_space=ignore_space))
                
            for hang in hangs:
                hang_body = hang.findtext("항내용", "") or ""
                hang_hit = contains_query(hang_body, normalized_query, ignore_space=ignore_space)
                hang_chunks = []
                lower_hit = False
                
                for ho in hang.findall("호"):
                    ho_body = ho.findtext("호내용", "") or ""
                    if contains_query(ho_body, normalized_query, ignore_space=ignore_space):
                        lower_hit = True
                        hang_chunks.append("&nbsp;&nbsp;" + highlight(ho_body, normalized_query, ignore_space=ignore_space))
                    for mok in ho.findall("목"):
                        for m in mok.findall("목내용"):
                            if m.text and contains_query(m.text, normalized_query, ignore_space=ignore_space):
                                lines = [line.strip() for line in m.text.splitlines() if line.strip()]
                                lines = [highlight(line, normalized_query, ignore_space=ignore_space) for line in lines]
                                if lines:
                                    lower_hit = True
                                    hang_chunks.append("<div style='margin:0;padding:0'>" + "<br>".join("&nbsp;&nbsp;&nbsp;&nbsp;" + line for line in lines) + "</div>")
                                    
                if hang_hit or lower_hit:
                    if not body_hit and not first_hang_attached:
                        joined = f"{highlight(jo_body, normalized_query, ignore_space=ignore_space)} {highlight(hang_body, normalized_query, ignore_space=ignore_space)}".strip()
                        output_chunks.append(joined)
                        first_hang_attached = True
                    elif not first_hang_attached:
                        output_chunks.append(highlight(hang_body, normalized_query, ignore_space=ignore_space))
                        first_hang_attached = True
                    else:
                        output_chunks.append(highlight(hang_body, normalized_query, ignore_space=ignore_space))
                    output_chunks.extend(hang_chunks)
                    
            if output_chunks:
                if jo_body:
                    law_results.append("<br>".join(output_chunks))
                else:
                    law_results.append(f"<b>{article_id}</b><br>" + "<br>".join(output_chunks))
                    
        if law_results:
            result_dict[law["법령명"]] = law_results
            
    return result_dict


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("사용법: python law_processor.py <명령> <검색어> [바꿀단어]")
        raise SystemExit(1)
    command = sys.argv[1]
    search_word = sys.argv[2]
    if command == "search":
        results = run_search_logic(search_word)
        for law_name, snippets in results.items():
            print(f"## {law_name}")
            for snippet in snippets:
                print(snippet)
                print("---")
    elif command == "amend":
        if len(sys.argv) < 4:
            print("바꿀단어를 입력하세요.")
            raise SystemExit(1)
        replace_word = sys.argv[3]
        results = run_amendment_logic(search_word, replace_word)
        for result in results:
            print(result)
            print()
    else:
        print(f"알 수 없는 명령: {command}")
        raise SystemExit(1)
