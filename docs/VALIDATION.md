# 验证记录

2026-11-17，本地Windows、Python 3.12。

- `python -m pytest portfolio_tests -q`：15项通过。只指新增套件。
- 实际Edge浏览器：审核门槛、审核通过、报告下载及刷新恢复通过。
- 界面截图来自本机实际运行，无真实账户或私有业务数据。
- GitHub Actions未运行。未进行公网生产部署、多用户安全认证或真实业务收益验证。

## 边界

- 这是固定拓扑的单工作流，不是分布式多Agent系统，也不包含模型训练或RAG。
- 未配置真实模型密钥。在线协议以mock HTTP响应测试，不能证明真实供应商兼容性。
- CSV为人工构造数据；CSV行和状态保存在本机SQLite，不能上传到公共仓库。
- 在线配置读取LLM_BASE_URL/LLM_MODEL/LLM_API_KEY，只向模型发送分析问题；不在检查点中保存密钥。
- 上游原始研究助手有独立依赖；运行新增项目只需requirements-portfolio.txt。
