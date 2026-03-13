import streamlit as st
import os
import importlib.util

st.set_page_config(
    layout="wide",
    menu_items={},
    page_icon="📘",
)

st.markdown("<h1 style='font-size:20px;'>📘 부칙개정 도우미 (v.1.2)</h1>", unsafe_allow_html=True)

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
processor_path = os.path.join(base_dir, "law_processor.py")
spec = importlib.util.spec_from_file_location("law_processor", processor_path)
law_processor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(law_processor)

run_amendment_logic = law_processor.run_amendment_logic
run_search_logic = law_processor.run_search_logic

with st.expander("ℹ️ 사용법 안내"):
    st.markdown(
        """
1. 이 앱은 이 앱은 다음 두 가지 기능을 제공합니다:

  가. <문자열 검색>: 사용자가 입력한 검색어가 포함된 법률 조항을 반환합니다.
     - 공백을 포함한 문자열을 검색할 수 있습니다.
     - 기본값은 <공백 무시 검색>이며, 필요하면 <공백 정확히 일치>를 선택할 수 있습니다.
     - 검색 범위는 <본문만> 또는 <제목+본문> 중에서 선택할 수 있습니다.
     - 다중검색어 및 논리연산자(AND, OR, NOT 등)는 지원하지 않습니다.
     - 입력한 문자열과 정확히 일치하는 문자열만을 반환합니다. "큰따옴표"는 필요하지 않습니다. 
     
  나. <개정문 생성>: 특정 문자열을 다른 문자열로 교체하는 부칙 개정문을 자동 생성합니다.
     - 21번째 결과물부터는 원문자가 아닌 괄호숫자로 항목 번호가 표기됩니다. 오류가 아닙니다.
     - <찾을 문자열>은 기본값이 <공백 무시 검색>이며, 필요하면 <공백 정확히 일치>를 선택할 수 있습니다.
     - <바꿀 문자열>은 입력한 그대로 사용합니다.
     - <배제할 법률>에 입력된 법률은 개정문 생성 목록에서 제외됩니다. 빈칸으로 두면 <찾을 문자열>이 포함된 모든 법률에 대해 개정문을 작성합니다.
     - <배제할 법률>에 입력된 법률명은 공백을 무시합니다. 
       (예) '개인정 보보호 법', '개인 정보 보호 법' 을 입력하여도 모두 '개인정보 보호법'으로 인식되어 해당 법률이 개정문 작성 대상에서 제외됩니다. 

2. 입력 편의를 위한 사항
- 가운뎃점(U+318D, 법제처 사이트에서 사용)을 입력해야 하는 경우 샵(#)으로 대체할 수 있습니다.
- 낫표(「」)대신 중괄호({})로 대체할 수 있습니다.
  (예) '{우체국예금#보험에 관한 법률} 제1조에 따른'을 입력하면 '「우체국예금#보험에 관한 법률」 제1조에 따른'을 검색하여 반환합니다.

3. 기타
- 이 앱은 2025.5.에 제작한 <부칙개정 도우마> v1.1.에서 입력편의성과 속도를 아주 약간 개선한 마이너체인지 버전입니다. 거의 동일합니다.
- v.1.1은 작년 국가정보자원관리원 화재 이후 작동하지 않아 링크를 삭제하였습니다. 새 버전을 이용해 주세요!
- 이 앱은 현행 법률의 법률 본문을 기준으로 검색합니다. 헌법, 폐지법률, 시행령, 시행규칙, 행정규칙은 검색하지 않습니다. 법률의 부칙 부분도 검색 대상에서 제외하였습니다.
- 이 앱은 업무망에서는 작동하지 않습니다. 인터넷망에서 사용해주세요.
- 속도가 느릴 수 있습니다.

- 오류가 있을 수 있습니다. 오류를 발견하시거나 개선 아이디어가 있으신 분께서는 사법법제과 김재우(jwkim@assembly.go.kr)에게 알려주시면 커피쿠폰을 드려요 :-) 
(2026.3.)
        """
    )

st.header("🔍 문자열 검색")
search_query = st.text_input("검색어 입력", key="search_query")
search_scope = st.radio(
    "검색 범위",
    ["본문만", "제목+본문"],
    index=0,
    horizontal=True,
    key="search_scope",
)
search_space_mode = st.radio(
    "공백 처리",
    ["공백 무시", "공백 정확히 일치"],
    index=0,
    horizontal=True,
    key="search_space_mode",
)
do_search = st.button("검색 시작")
if do_search and search_query:
    with st.spinner("🔍 검색 중..."):
        result = run_search_logic(
            search_query,
            unit="법률",
            include_title=(search_scope == "제목+본문"),
            ignore_space=(search_space_mode == "공백 무시"),
        )
        st.success(f"{len(result)}개의 법률을 찾았습니다")
        for law_name, sections in result.items():
            with st.expander(f"📄 {law_name}"):
                for html in sections:
                    st.markdown(html, unsafe_allow_html=True)

st.header("✏️ 개정문 생성")
find_word = st.text_input("찾을 문자열")
replace_word = st.text_input("바꿀 문자열")
amend_space_mode = st.radio(
    "찾을 문자열 공백 처리",
    ["공백 무시", "공백 정확히 일치"],
    index=0,
    horizontal=True,
    key="amend_space_mode",
)
exclude_laws = st.text_input(
    "배제할 법률 (쉼표로 구분)",
    help="결과에서 제외할 법률 이름을 쉼표(,)로 구분하여 입력하세요.",
)
do_amend = st.button("개정문 생성")

if do_amend and find_word and replace_word:
    with st.spinner("🛠 개정문 생성 중..."):
        exclude_law_list = [law.strip() for law in exclude_laws.split(',')] if exclude_laws else []
        result = run_amendment_logic(
            find_word,
            replace_word,
            exclude_law_list,
            ignore_space=(amend_space_mode == "공백 무시"),
        )
        st.success("개정문 생성 완료")
        for amend in result:
            st.markdown(amend, unsafe_allow_html=True)
