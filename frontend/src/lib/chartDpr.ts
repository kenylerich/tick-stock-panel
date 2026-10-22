/**
 * 图表 HiDPI 采样率 — 页面缩放 (pageZoom 的 transform: scale) 下保持图表清晰。
 *
 * 背景: #root 的 transform: scale(z) 对文字/SVG 是矢量放大, 但 canvas 图表
 * (ECharts/lightweight-charts) 按布局像素 × window.devicePixelRatio 光栅化后再
 * 被 GPU 拉伸, 等效采样率变为 dpr/z, z>1 时 K 线/分时等图表发虚。
 *
 * 处理: ECharts 初始化与 resize 都显式传 devicePixelRatio = dpr × 页面缩放
 * (上限 CHART_DPR_MAX, 防止超大 canvas 占用过多显存/内存)。
 * lightweight-charts v4 无该选项, 其模糊程度有限 (dpr=2 时 z≤1.5 仍有 1.33 倍采样)。
 */
import * as echarts from 'echarts'
import { getPageScale } from '@/lib/pageZoom'

/** 采样率上限: 4K 宽图表 ×3 已接近浏览器单 canvas 尺寸安全边界。 */
export const CHART_DPR_MAX = 3

/** 图表应使用的 devicePixelRatio: 页面放大 (z>1) 时按比例补偿, 缩小不降采样。 */
export function chartDevicePixelRatio(): number {
  const dpr = window.devicePixelRatio || 1
  const scale = getPageScale()
  return scale > 1 ? Math.min(dpr * scale, CHART_DPR_MAX) : dpr
}

/** 统一 ECharts 初始化入口: canvas 渲染 + HiDPI 采样率。 */
export function initEChart(el: HTMLElement | null): echarts.ECharts {
  return echarts.init(el, undefined, {
    renderer: 'canvas',
    devicePixelRatio: chartDevicePixelRatio(),
  })
}

/** 统一 resize 入口: 页面缩放变更后随 resize 事件调用, 重栅格化为新采样率。
 *
 * ECharts 5.5 的 resize() 不支持 devicePixelRatio(v6 才加入 ResizeOpts);
 * v5 的等效做法是同步 zrender CanvasPainter.dpr 再触发 resize — painter
 * 重建 canvas 尺寸时按 this.dpr 计算, 从而按新采样率重栅格化。
 */
export function resizeEChart(chart: echarts.ECharts | null | undefined): void {
  if (!chart || chart.isDisposed()) return
  const painter = (chart.getZr() as { painter?: { dpr?: number } }).painter
  const dpr = chartDevicePixelRatio()
  if (painter && painter.dpr !== undefined) painter.dpr = dpr
  chart.resize()
}
