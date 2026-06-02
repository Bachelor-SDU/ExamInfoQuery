import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# 1. 页面基本配置
st.set_page_config(page_title="考务信息查询系统")

# ==========================================
# 请替换为你的真实 Google 表格链接
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1y2YznN7bDOJmcVn25M6WciBJNiHIpnxzel0QSvj7VBM/edit?gid=0#gid=0"


# ==========================================

# 2. 清理电话号码的工具函数（防止Excel将电话读成浮点数如 13800000000.0）
def clean_phone(phone_val):
    if pd.isna(phone_val):
        return ""
    p_str = str(phone_val).strip()
    if p_str.endswith('.0'):
        p_str = p_str[:-2]
    return p_str


# 3. 核心功能：读取表格并解析宽表结构
@st.cache_data(ttl=86400)
def load_data_from_sheets():
    # 连接到 Google Sheets
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(spreadsheet=SPREADSHEET_URL)

    # 获取表头，并剔除 Pandas 自动生成的后缀 (例如将 "命题教师.1" 还原为 "命题教师")
    raw_columns = [str(c).split('.')[0].strip() for c in df.columns]

    users_dict = {}  # 存储结构： { "姓名_尾号": {name, phone, email, assignments: [{科目, 角色, 伙伴[]}]} }

    # 遍历表格的每一行（每一个学科）
    for idx, row in df.iterrows():
        subject = str(row.iloc[0]).strip()
        if pd.isna(row.iloc[0]) or not subject or subject.lower() == 'nan':
            continue  # 跳过空行

        creators = []
        reviewers = []

        # 横向扫描当前行的列
        i = 1
        while i < len(raw_columns) - 2:
            col_name = raw_columns[i]

            # 如果侦测到是教师列，则向后读取对应的电话和邮箱
            if col_name in ['命题教师', '审题教师']:
                t_name = str(row.iloc[i]).strip()
                t_phone = clean_phone(row.iloc[i + 1])
                t_email = str(row.iloc[i + 2]).strip()

                # 如果该单元格有名字，则记录下来
                if t_name and t_name.lower() != 'nan':
                    teacher_info = {'name': t_name, 'phone': t_phone, 'email': t_email, 'role_type': col_name}
                    if col_name == '命题教师':
                        creators.append(teacher_info)
                    else:
                        reviewers.append(teacher_info)
                # 跳过对应的电话和邮箱列，继续往后扫描
                i += 3
            else:
                # 容错处理：如果列名不对齐，逐列步进
                i += 1

        # 为当前学科的老师进行互相关联配对
        all_teachers_in_subject = creators + reviewers

        for t in all_teachers_in_subject:
            # 使用 "姓名_电话后4位" 生成唯一ID (兼容不同老师同名的情况)
            phone_tail = t['phone'][-4:] if len(t['phone']) >= 4 else t['phone']
            uid = f"{t['name']}_{phone_tail}"

            # 如果是首次遇到该老师，初始化信息
            if uid not in users_dict:
                users_dict[uid] = {
                    'name': t['name'],
                    'phone': t['phone'],
                    'email': t['email'],
                    'assignments': []  # 记录该老师负责的科目及配对人员
                }

            # 寻找该老师在当前科目的“配对伙伴”
            partners = []
            if t['role_type'] == '命题教师':
                current_role = "命题教师"
                # 命题教师的伙伴是该科目的所有【审题教师】
                for r in reviewers:
                    partners.append({"role": "审题教师", "info": r})
            else:
                current_role = "审题教师"
                # 审题教师的伙伴是该科目的所有【命题教师】
                for c in creators:
                    partners.append({"role": "命题教师", "info": c})

            # 将该学科任务追加到该老师的名下
            users_dict[uid]['assignments'].append({
                "subject": subject,
                "role": current_role,
                "partners": partners
            })

    return users_dict


# --- 数据加载机制 ---
try:
    with st.spinner('正在同步教务处最新数据...'):
        users_data = load_data_from_sheets()
except Exception as e:
    st.error(f"无法读取表格数据，请检查 Secrets 密钥和 Google 表格权限。错误详情: {e}")
    st.stop()


# --- 身份校验逻辑 ---
def authenticate(input_name, input_phone4):
    target_uid = f"{input_name}_{input_phone4}"
    if target_uid in users_data:
        return target_uid, users_data[target_uid]
    return None, None


# ==========================================
#                UI 界面部分
# ==========================================

st.title("考务信息查询系统")

# 状态初始化
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# 【未登录界面】
if not st.session_state.logged_in:
    st.info("身份校验通过后，将展示与您相关的教师信息。")
    with st.form("login_form"):
        input_name = st.text_input("您的姓名")
        input_phone4 = st.text_input("手机号后4位", max_chars=4, type="password")
        submitted = st.form_submit_button("验证身份，查看匹配信息")

        if submitted:
            if not input_name or len(input_phone4) != 4:
                st.error("请输入完整的姓名和4位手机尾号。")
            else:
                uid, uinfo = authenticate(input_name.strip(), input_phone4.strip())
                if uid:
                    st.session_state.logged_in = True
                    st.session_state.current_user_id = uid
                    st.session_state.current_user_info = uinfo
                    st.rerun()
                else:
                    st.error("校验失败！未找到您的信息，请确认姓名及手机尾号是否正确。")

# 【已登录界面】
else:
    u_info = st.session_state.current_user_info

    st.success(f"身份验证成功！欢迎您，{u_info['name']} 老师")
    st.write("---")

    # 遍历展示该老师参与的所有科目（支持一位老师同时负责多门学科）
    for assign in u_info['assignments']:
        st.write(f"您是{assign['subject']}科目的**{assign['role']}**")

        if not assign['partners']:
            st.warning("系统尚未给该科目分配对应的配对老师。")
        else:
            st.write(f"您需要关注的教师信息（悬浮在灰色框右上角可一键复制）：")
            # 遍历该科目的所有配对老师
            for partner in assign['partners']:
                p_role = partner['role']
                p_info = partner['info']

                with st.expander(f"{p_role} : {p_info['name']}", expanded=True):
                    # 使用 st.code 生成纯净的自带复制按钮的代码块
                    copy_text = f"姓名：{p_info['name']}\n电话：{p_info['phone']}\n邮箱：{p_info['email']}"
                    st.code(copy_text, language=None)

        st.write("---")  # 科目分割线

    # 退出登录按钮
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("退出登录", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.current_user_id = None
            st.session_state.current_user_info = None
            st.rerun()