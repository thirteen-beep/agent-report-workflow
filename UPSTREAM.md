# 上游来源与改造范围

来源：https://github.com/langchain-ai/local-deep-researcher

基线提交：`03537326ffa0dd90c9702bece2f3aeba5d84162a`。保留完整Git历史和原样LICENSE，新增代码通过AI辅助实现。

1. 适配上游graph.py/state.py中的StateGraph与状态传递模式，新增plan→execute→review→finish业务图。
2. 使用LangGraph interrupt及SqliteSaver实现人工审核、线程隔离、重启恢复；审核拒绝时不生成报告。
3. 规划器仅能选择daily_summary/channel_summary两个白名单工具，每次计划最多两项；指标由Python计算。
4. 可选兼容模型HTTP规划接口，失败有限重试；默认明确标注离线规则路由。增加Streamlit界面与Markdown下载。

原始README在UPSTREAM_README文件中保留。原框架、库和样例的原有能力属于上游；本项目新增业务和测试见以上清单。
