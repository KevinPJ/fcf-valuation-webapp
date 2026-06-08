# 部署清单

目标：把本项目发布成一个真实网站，由 FastAPI 后端联网调用 AkShare 获取 A 股行情和财务报表，前端从同域 `/api/*` 获取数据。

## 推荐方案：Render

1. 创建一个 GitHub 仓库，并把本项目所有文件推送上去。
2. 登录 Render，选择 `New` -> `Blueprint`。
3. 选择 GitHub 仓库。
4. Render 会读取 `render.yaml`，按 Docker 方式构建服务。
5. 构建完成后，打开 Render 给出的 `https://...onrender.com` 网址。
6. 用 `https://...onrender.com/api/health` 检查服务状态。
7. 用 `https://...onrender.com/api/data-health` 检查 AkShare 是否能联网返回真实行情数据。
8. 在页面输入 `000001` 等 A 股代码测试真实数据。

也可以从 README 的 `Deploy to Render` 按钮进入 Render 创建流程，但仍需要先把项目放到 GitHub 仓库。

## 验收标准

- `/api/health` 返回 `{"status":"ok","data_source":"AkShare",...}`。
- `/api/data-health` 返回东方财富或 AkShare 真实数据接口名称、行数和样本字段。
- `/api/company/000001` 返回真实公司名称、最新价和市值字段。
- `/api/financials/000001` 返回 AkShare 报表时序数据。
- 首页加载后能看到估值参数面板、估值结果卡片、历史指标图、FCF 预测表和敏感性表。
- 如果 AkShare 网络或字段失败，页面显示错误，不使用演示数据冒充真实数据。

更完整的上线检查见 [PRODUCTION_CHECKS.md](PRODUCTION_CHECKS.md)。

## 注意事项

- AkShare 是公开数据接口，稳定性、字段名和访问频率可能变化。
- 免费托管平台冷启动较慢，首次打开可能需要等待几十秒。
- 本项目输出为 `screen-grade` 研究工具，不是可直接交易的决策级模型。
