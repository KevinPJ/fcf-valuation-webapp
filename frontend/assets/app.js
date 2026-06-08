const { useEffect, useMemo, useRef, useState } = React;

const billion = 100000000;

const defaultInputs = {
  symbol: "000001",
  stage1Growth: 8,
  terminalGrowth: 2.5,
  wacc: 9,
  forecastYears: 5,
  baseFcfOverride: "",
  netDebtOverride: "",
  sharesOverride: "",
};

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${formatNumber(value / billion, 2)} 亿`;
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${formatNumber(value * 100, 1)}%`;
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function loadData(payload) {
  const [companyResult, financialsResult, valuationResult] = await Promise.all([
    api(`/api/company/${payload.symbol}`),
    api(`/api/financials/${payload.symbol}`),
    api("/api/valuation", { method: "POST", body: JSON.stringify(payload) }),
  ]);
  return { companyResult, financialsResult, valuationResult };
}

function Chart({ option }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !window.echarts) return undefined;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [option]);

  return <div className="chart" ref={ref} />;
}

function InputPanel({ inputs, setInputs, loading, onSubmit }) {
  const update = (key) => (event) => setInputs({ ...inputs, [key]: event.target.value });

  return (
    <aside className="panel">
      <div className="panel-header">
        <h2>估值参数</h2>
        <p>FCFF 企业价值法，金额覆盖项按人民币亿元输入。</p>
      </div>
      <form className="form" onSubmit={onSubmit}>
        <div className="field">
          <label>股票代码</label>
          <input value={inputs.symbol} onChange={update("symbol")} placeholder="例如 000001" />
        </div>
        <div className="grid-2">
          <div className="field">
            <label>一阶 FCF 增速</label>
            <input type="number" step="0.1" value={inputs.stage1Growth} onChange={update("stage1Growth")} />
          </div>
          <div className="field">
            <label>永续增速</label>
            <input type="number" step="0.1" value={inputs.terminalGrowth} onChange={update("terminalGrowth")} />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label>WACC</label>
            <input type="number" step="0.1" value={inputs.wacc} onChange={update("wacc")} />
          </div>
          <div className="field">
            <label>预测年数</label>
            <input type="number" min="1" max="15" value={inputs.forecastYears} onChange={update("forecastYears")} />
          </div>
        </div>
        <div className="field">
          <label>基准 FCF 覆盖</label>
          <input type="number" step="0.01" value={inputs.baseFcfOverride} onChange={update("baseFcfOverride")} placeholder="留空使用真实数据源，单位：亿元" />
        </div>
        <div className="grid-2">
          <div className="field">
            <label>净债务覆盖</label>
            <input type="number" step="0.01" value={inputs.netDebtOverride} onChange={update("netDebtOverride")} placeholder="亿元" />
          </div>
          <div className="field">
            <label>股本覆盖</label>
            <input type="number" step="0.01" value={inputs.sharesOverride} onChange={update("sharesOverride")} placeholder="亿股" />
          </div>
        </div>
        <button className="submit" disabled={loading}>{loading ? "计算中..." : "重新计算"}</button>
        <p className="hint">WACC 必须高于永续增速。缺失字段可用覆盖项补齐，覆盖项会直接参与估值。</p>
      </form>
    </aside>
  );
}

function MetricCards({ company, valuation }) {
  const upsideClass = valuation?.upside >= 0 ? "upside-positive" : "upside-negative";
  return (
    <div className="metric-grid">
      <div className="card metric">
        <span>DCF 每股价值</span>
        <strong>{valuation ? `${formatNumber(valuation.value_per_share, 2)} 元` : "-"}</strong>
        <small>状态：{valuation?.status || "-"}</small>
      </div>
      <div className="card metric">
        <span>最新价格</span>
        <strong>{company?.latest_price ? `${formatNumber(company.latest_price, 2)} 元` : "-"}</strong>
        <small>{company?.name || "等待查询"}</small>
      </div>
      <div className="card metric">
        <span>隐含空间</span>
        <strong className={upsideClass}>{valuation ? formatPercent(valuation.upside) : "-"}</strong>
        <small>相对最新行情</small>
      </div>
      <div className="card metric">
        <span>企业价值</span>
        <strong>{valuation ? formatMoney(valuation.enterprise_value) : "-"}</strong>
        <small>股权价值 {valuation ? formatMoney(valuation.equity_value) : "-"}</small>
      </div>
    </div>
  );
}

function HistoricalCharts({ financials }) {
  const option = useMemo(() => {
    const periods = financials?.periods || [];
    return {
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 52, right: 24, top: 48, bottom: 36 },
      xAxis: { type: "category", data: periods.map((item) => item.period) },
      yAxis: { type: "value", axisLabel: { formatter: (value) => `${value}亿` } },
      series: [
        {
          name: "营业收入",
          type: "bar",
          data: periods.map((item) => item.revenue ? +(item.revenue / billion).toFixed(2) : null),
          itemStyle: { color: "#567c9f" },
        },
        {
          name: "自由现金流",
          type: "line",
          smooth: true,
          data: periods.map((item) => item.free_cash_flow ? +(item.free_cash_flow / billion).toFixed(2) : null),
          itemStyle: { color: "#147d64" },
        },
        {
          name: "净利润",
          type: "line",
          smooth: true,
          data: periods.map((item) => item.net_income ? +(item.net_income / billion).toFixed(2) : null),
          itemStyle: { color: "#9a6700" },
        },
      ],
    };
  }, [financials]);

  return <Chart option={option} />;
}

function ForecastTable({ valuation }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>年份</th>
            <th>FCF</th>
            <th>折现因子</th>
            <th>现值</th>
          </tr>
        </thead>
        <tbody>
          {(valuation?.forecast || []).map((row) => (
            <tr key={row.year}>
              <td>第 {row.year} 年</td>
              <td>{formatMoney(row.fcf)}</td>
              <td>{formatNumber(row.discount_factor, 3)}</td>
              <td>{formatMoney(row.present_value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SensitivityTable({ valuation }) {
  const grouped = useMemo(() => {
    const rows = valuation?.sensitivity || [];
    const waccs = [...new Set(rows.map((row) => row.wacc))];
    const growths = [...new Set(rows.map((row) => row.terminal_growth))];
    return { rows, waccs, growths };
  }, [valuation]);

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>WACC / 永续</th>
            {grouped.growths.map((growth) => <th key={growth}>{formatPercent(growth)}</th>)}
          </tr>
        </thead>
        <tbody>
          {grouped.waccs.map((wacc) => (
            <tr key={wacc}>
              <td>{formatPercent(wacc)}</td>
              {grouped.growths.map((growth) => {
                const cell = grouped.rows.find((row) => row.wacc === wacc && row.terminal_growth === growth);
                return <td key={`${wacc}-${growth}`}>{cell?.value_per_share == null ? "-" : formatNumber(cell.value_per_share, 2)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BridgeTable({ valuation }) {
  const rows = valuation
    ? [
        ["基准 FCF", valuation.base_fcf],
        ["终值", valuation.terminal_value],
        ["企业价值", valuation.enterprise_value],
        ["净债务", valuation.net_debt],
        ["股权价值", valuation.equity_value],
        ["股本", valuation.shares],
      ]
    : [];

  return (
    <div className="table-wrap">
      <table>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{label === "股本" ? `${formatNumber(value / billion, 2)} 亿股` : formatMoney(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ErrorPanel({ message }) {
  if (!message) return null;
  return (
    <div className="error">
      <strong>真实数据连接失败</strong>
      <p>{message}</p>
      <p>请先检查 <code>/api/health</code>，再检查 <code>/api/data-health</code>。如果前者正常但后者失败，通常是部署环境无法访问 AkShare 数据源。</p>
    </div>
  );
}

function App() {
  const [inputs, setInputs] = useState(defaultInputs);
  const [company, setCompany] = useState(null);
  const [financials, setFinancials] = useState(null);
  const [valuation, setValuation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event?.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload = {
        symbol: inputs.symbol.trim(),
        stage1Growth: Number(inputs.stage1Growth) / 100,
        terminalGrowth: Number(inputs.terminalGrowth) / 100,
        wacc: Number(inputs.wacc) / 100,
        forecastYears: Number(inputs.forecastYears),
      };
      if (inputs.baseFcfOverride !== "") payload.baseFcfOverride = Number(inputs.baseFcfOverride) * billion;
      if (inputs.netDebtOverride !== "") payload.netDebtOverride = Number(inputs.netDebtOverride) * billion;
      if (inputs.sharesOverride !== "") payload.sharesOverride = Number(inputs.sharesOverride) * billion;

      const { companyResult, financialsResult, valuationResult } = await loadData(payload);
      setCompany(companyResult);
      setFinancials(financialsResult);
      setValuation(valuationResult);
    } catch (err) {
      setCompany(null);
      setFinancials(null);
      setValuation(null);
      setError(err.message || "未知错误");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    submit();
  }, []);

  const warnings = [...(company?.warnings || []), ...(financials?.warnings || []), ...(valuation?.warnings || [])];
  const uniqueWarnings = [...new Set(warnings)];

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <h1>A股自由现金流估值模型</h1>
            <p>实时连接后端 AkShare 数据源 · FCFF 企业价值法 · screen-grade 投资研究工具</p>
          </div>
          <div className="status-pill"><span className="status-dot" />{valuation?.as_of || "等待计算"}</div>
        </div>
      </header>

      <div className="workspace">
        <InputPanel inputs={inputs} setInputs={setInputs} loading={loading} onSubmit={submit} />
        <section className="content">
          <ErrorPanel message={error} />
          <MetricCards company={company} valuation={valuation} />

          <section className="section">
            <div className="section-header">
              <h2>历史指标时序</h2>
              <p>营业收入、净利润和自由现金流，单位：亿元。</p>
            </div>
            <div className="section-body">
              {financials ? <HistoricalCharts financials={financials} /> : <div className="empty">等待数据</div>}
            </div>
          </section>

          <div className="two-col">
            <section className="section">
              <div className="section-header">
                <h2>FCF 预测</h2>
                <p>按一阶增速推演并折现。</p>
              </div>
              <div className="section-body">
                <ForecastTable valuation={valuation} />
              </div>
            </section>
            <section className="section">
              <div className="section-header">
                <h2>估值桥</h2>
                <p>企业价值到股权价值。</p>
              </div>
              <div className="section-body">
                <BridgeTable valuation={valuation} />
              </div>
            </section>
          </div>

          <section className="section">
            <div className="section-header">
              <h2>WACC / 永续增速敏感性</h2>
              <p>单元格为 DCF 每股价值，单位：元。</p>
            </div>
            <div className="section-body">
              <SensitivityTable valuation={valuation} />
            </div>
          </section>

          <section className="section">
            <div className="section-header">
              <h2>数据与模型警告</h2>
              <p>公开数据和字段映射可能变化，结果不作为直接投资决策级输出。</p>
            </div>
            <div className="section-body">
              {uniqueWarnings.length ? (
                <ul className="warning-list">
                  {uniqueWarnings.map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
              ) : (
                <p className="hint">暂无警告。</p>
              )}
            </div>
          </section>
        </section>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
