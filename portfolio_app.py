"""Single-user local UI for the checkpointed workflow."""
import os
from pathlib import Path
import tempfile
import uuid
import streamlit as st
from langgraph.types import Command
from report_agent.workflow import load_csv, model_plan, open_workflow

st.set_page_config(page_title='运营报告工作流', layout='wide')
st.title('运营报告工作流')
st.caption('LangGraph · SQLite 检查点 · 人工审核 · 默认离线规则演示，无模型推理')
database = Path(os.environ.get('REPORT_CHECKPOINT_DB', '.data/checkpoints.sqlite'))
thread = st.text_input('会话 ID', value='ui-demo')
online = st.checkbox('在线模型规划（需要环境变量配置）')
question = st.text_input('分析问题', value='按渠道汇总转化')
upload = st.file_uploader('可选：上传 day/channel/visits/conversions CSV', type=['csv'])
st.caption('默认使用人工构造示例。检查点保存在本机，包含上传数据。在线模式只发送分析问题。')
if not thread.strip() or len(thread) > 100:
    st.warning('请输入不超过100字符的会话 ID。')
    st.stop()
config = {'configurable': {'thread_id': thread}, 'recursion_limit': 12}
try:
    with open_workflow(database, model_plan if online else None) as graph:
        if st.button('开始分析'):
            if graph.get_state(config).values:
                st.warning('该会话已有记录，请更换会话 ID，或查看下方历史与待审核结果。')
            else:
                if upload:
                    if upload.size > 5_000_000:
                        raise ValueError('CSV超过5 MB')
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory)/'upload.csv'
                        path.write_bytes(upload.getvalue())
                        rows = load_csv(path)
                else:
                    rows = load_csv(Path(__file__).with_name('examples')/'channel_events.csv')
                graph.invoke({'question': question, 'rows': rows, 'trace': []}, config)
        snapshot = graph.get_state(config)
        if snapshot.values:
            st.write('运行模式：'+snapshot.values.get('mode', 'unknown'))
            st.json(snapshot.values.get('results', {}))
            if snapshot.next == ('review',):
                st.info('计算完成，等待人工审核。审核前不会生成报告。')
                yes, no = st.columns(2)
                approve = yes.button('审核通过')
                reject = no.button('拒绝生成')
                if approve or reject:
                    graph.invoke(Command(resume={'approve': approve}), config)
                    snapshot = graph.get_state(config)
            report = snapshot.values.get('report')
            if report:
                st.markdown(report)
                st.download_button('下载 Markdown 报告', report, file_name='operations-report.md')
            elif snapshot.values.get('approved') is False:
                st.warning('报告已拒绝生成。')
            st.write('执行记录：'+' → '.join(snapshot.values.get('trace', [])))
except (ValueError, OSError) as exc:
    st.error(str(exc))
