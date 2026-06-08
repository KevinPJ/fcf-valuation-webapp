# A股自由现金流估值模型

本项目是一个可部署的网站：FastAPI 后端封装 AkShare 真实财经数据获取和 FCFF DCF 计算，React 前端展示参数输入、估值结果、历史指标图、预测表和敏感性表。

## 运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。

## 部署成真实网站

推荐用 Render、Railway、Fly.io 或任何支持 Docker 的云平台部署。
详细步骤见 [DEPLOY.md](DEPLOY.md)。
上线后检查见 [PRODUCTION_CHECKS.md](PRODUCTION_CHECKS.md)。

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

### Render

1. 把本项目上传到 GitHub。
2. 在 Render 新建 `Blueprint` 或 `Web Service`。
3. 选择本仓库；Render 会读取 `render.yaml` 和 `Dockerfile`。
4. 部署完成后访问 Render 分配的 `https://...onrender.com` 链接。
5. 健康检查地址：`/api/health`。
6. 真实数据源检查地址：`/api/data-health`。

### Docker

```powershell
docker build -t fcf-valuation-webapp .
docker run --rm -p 8000:8000 fcf-valuation-webapp
```

## API

- `GET /api/company/{symbol}`：公司名称、最新价格、交易日、市值。
- `GET /api/financials/{symbol}`：收入、净利润、经营现金流、资本开支、FCF、现金、债务、股本等时序数据。
- `POST /api/valuation`：输入股票代码、一阶增速、永续增速、WACC 和可选覆盖项，返回 DCF 估值、预测表和敏感性矩阵。
- `GET /api/health`：部署健康检查。
- `GET /api/data-health`：实际调用东方财富直连接口，失败后回退 AkShare 单股票接口，检查真实财经数据源连通性。

## 说明

- 首版优先支持 A 股。
- 东方财富和 AkShare 都不可用时，后端会返回错误；线上版本不会用演示数据冒充真实数据。
- 估值结果标记为 `screen-grade`，不作为直接投资决策级输出。
- 前端使用 CDN 加载 React、Babel 和 ECharts；部署环境需要允许浏览器访问这些静态库，或后续改为本地打包前端资产。
