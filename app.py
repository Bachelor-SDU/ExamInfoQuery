import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# 1. 页面基本配置
st.set_page_config(page_title="信息查询系统")

# ==========================================
# 请替换为你的真实 Google 表格链接
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1y2YznN7bDOJmcVn25M6WciBJNiHIpnxzel0QSvj7VBM/edit?gid=0#gid=0"

# ==========================================

# 2. 清理电话号码的工具函数（防范浮点数、小数、空格问题）
def clean_phone(phone_val):
    if pd.isna(phone_val) or str(phone_val).lower() == 'nan':
        return ""
    if isinstance(phone_val, float):
        p_str = f"{phone_val:.0f}"
    else:
        p_str = str(phone_val).strip()

    if p_str.endswith('.0'):
        p_str = p_str[:-2]
    return p_str.replace(" ", "")


# 3. 核心功能：读取表格并解析宽表结构（采用逐行向下扫描的智能引擎）
@st.cache_data(ttl=86400)  # 正式环境建议 86400 (24小时)，发布群聊前请自己先点开一次“预热”缓存
def load_data_from_sheets():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(spreadsheet=SPREADSHEET_URL)

    users_dict = {}
    current_grade = ""  # 用于记忆当前扫描到了哪个年级
    current_headers = []  # 用于记忆当前区块的表头顺序

    # 将被 Pandas 误吞的第一行（原本的列名）和底下的数据行合并，形成一个完整列表
    all_rows = [df.columns.tolist()] + df.values.tolist()

    # 像人眼一样自上而下逐行阅读
    for row in all_rows:
        # 获取每一行最左侧的第一个单元格内容
        cell_0 = str(row[0]).strip()

        # 过滤掉完全为空的行，或 Pandas 自动生成的 'Unnamed' 占位符
        if not cell_0 or cell_0.lower() == 'nan' or cell_0.startswith('Unnamed'):
            continue

        # 💡 情况 A：扫描到了年级行（合并单元格往往只在第一列有值）
        if '高' in cell_0 or '年级' in cell_0:
            current_grade = cell_0
            continue

        # 💡 情况 B：扫描到了表头行
        if cell_0 == '学科':
            # 更新当前的表头结构（去除 Pandas 可能加上的 .1 .2 后缀）
            current_headers = [str(c).split('.')[0].strip() for c in row]
            continue

        # 💡 情况 C：扫描到了真正的学科数据行（如 "语文", "数学"）
        if not current_headers:
            continue  # 如果格式混乱还没读到表头，先跳过

        subject = cell_0
        # 将 年级与学科 拼接显示，例如："高一 语文"
        full_subject_name = f"{current_grade} {subject}".strip()

        creators = []
        reviewers = []

        # 使用当前保存的表头，横向扫描此行的老师信息
        i = 1
        while i < len(current_headers) - 2 and i < len(row) - 2:
            col_name = current_headers[i]

            # 使用智能包容匹配：包含"命题"、"监考"、"审题"等关键字均可识别
            if '命题' in col_name or '监考' in col_name or '审题' in col_name:
                t_name = str(row[i]).strip()
                t_phone = clean_phone(row[i + 1])
                raw_email = str(row[i + 2]).strip()
                t_email = "" if raw_email.lower() == 'nan' or not raw_email else raw_email

                # 如果该单元格确实填了人名
                if t_name and t_name.lower() != 'nan':
                    teacher_info = {'name': t_name, 'phone': t_phone, 'email': t_email, 'role_type': col_name}

                    if '命题' in col_name:
                        creators.append(teacher_info)
                    else:
                        reviewers.append(teacher_info)

                # 老师+电话+邮箱是3列，所以往后跳3格
                i += 3
            else:
                # 容错：遇到乱七八糟的列名，步进1格继续找
                i += 1

        # 为当前学科的老师进行互相关联配对
        all_teachers_in_subject = creators + reviewers

        for t in all_teachers_in_subject:
            phone_tail = t['phone'][-4:] if len(t['phone']) >= 4 else t['phone']
            uid = f"{t['name']}_{phone_tail}"

            if uid not in users_dict:
                users_dict[uid] = {
                    'name': t['name'],
                    'phone': t['phone'],
                    'email': t['email'],
                    'assignments': []
                }

            partners = []

            if '命题' in t['role_type']:
                current_role = t['role_type']  # 直接显示表头原话，如"命题老师"
                for r in reviewers:
                    partners.append({"role": r['role_type'], "info": r})
            else:
                current_role = t['role_type']  # 如"监考老师"
                for c in creators:
                    partners.append({"role": c['role_type'], "info": c})

            # 追加任务时，放入拼接了年级的学科名
            users_dict[uid]['assignments'].append({
                "subject": full_subject_name,
                "role": current_role,
                "partners": partners
            })

    return users_dict


# --- 数据加载机制 ---
try:
    with st.spinner('正在同步最新数据...'):
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

st.title("信息查询系统")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.info("身份校验通过后，将展示您需要关注的教师信息。")

    with st.form("login_form"):
        input_name = st.text_input("您的姓名")
        input_phone4 = st.text_input("手机号后4位", max_chars=4, type="password")
        submitted = st.form_submit_button("验证身份，查看信息")

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

else:
    u_info = st.session_state.current_user_info

    st.success(f"身份验证成功！欢迎您，{u_info['name']} 老师！！")
    st.write("---")

    # 遍历展示该老师参与的所有科目
    for assign in u_info['assignments']:
        st.write(f"您是**{assign['subject']}**科目的**{assign['role']}**")

        if not assign['partners']:
            st.warning("系统数据出错，请联系管理员。")
        else:
            st.write("您需要关注的教师信息（悬浮在灰色框右上角可一键复制）：")
            for partner in assign['partners']:
                p_role = partner['role']
                p_info = partner['info']

                with st.expander(f"{p_role} : {p_info['name']}", expanded=True):
                    email_line = f"\n邮箱：{p_info['email']}" if p_info['email'] else ""
                    copy_text = f"姓名：{p_info['name']}\n电话：{p_info['phone']}{email_line}"
                    st.code(copy_text, language=None)

        st.write("---")

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("退出登录", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.current_user_id = None
            st.session_state.current_user_info = None
            st.rerun()