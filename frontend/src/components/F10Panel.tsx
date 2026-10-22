/**
 * F10 经营面板 (issue #5/#6): 主营构成 + 公司概况 + 同行清单。
 *
 * 数据经面板后端 /api/f10/* 代理(来源 AKShare 桥, 可插拔侧车)。
 * 桥不可达时显示引导文案而非空白; 主营构成展示最新报告期,
 * 分产品/分地区两组拆解(收入占比 + 毛利率)。
 */
import { useEffect, useMemo, useState } from 'react'
import { Building2, Users, AlertTriangle, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/cn'

interface ZygcItem {
  report_date?: string
  category?: string
  name?: string
  revenue?: number | null
  revenue_ratio?: number | null
  profit?: number | null
  profit_ratio?: number | null
  gross_margin?: number | null
}

interface F10State {
  zygc: { latest_date: string | null; periods: { report_date: string; items: ZygcItem[] }[] } | null
  profile: Record<string, string> | null
  peers: { industry?: string; degraded?: boolean; peers?: { symbol: string; name?: string }[] } | null
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}) as { detail?: string })
    throw new Error(detail.detail || `请求失败: ${res.status}`)
  }
  return res.json() as Promise<T>
}

const pct = (v: number | null | undefined, digits = 1): string =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`

const yi = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '—'
  return `${(v / 1e8).toFixed(1)}亿`
}

function SectionTitle({ icon: Icon, children }: { icon: typeof Building2; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 text-foreground">
      <Icon className="h-3.5 w-3.5 text-accent" />
      <span className="text-xs font-medium">{children}</span>
    </div>
  )
}

export function F10Panel({ symbol }: { symbol: string }) {
  const [state, setState] = useState<Partial<F10State>>({})
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.allSettled([
      fetchJson<F10State['zygc']>(`/api/f10/zygc/${symbol}`),
      fetchJson<{ profile: Record<string, string> }>(`/api/f10/profile/${symbol}`),
      fetchJson<F10State['peers']>(`/api/f10/peers/${symbol}`),
    ]).then(([zygc, profile, peers]) => {
      if (cancelled) return
      const next: Partial<F10State> = {}
      if (zygc.status === 'fulfilled') next.zygc = zygc.value
      if (profile.status === 'fulfilled') next.profile = profile.value.profile
      if (peers.status === 'fulfilled') next.peers = peers.value
      const failures = [zygc, profile, peers].filter(r => r.status === 'rejected') as PromiseRejectedResult[]
      // 三路全失败才视为整体错误(桥不可达); 部分失败保留其余段
      if (failures.length === 3) setError(failures[0].reason?.message || '数据获取失败')
      setState(next)
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [symbol, reloadKey])

  const groups = useMemo(() => {
    const latest = state.zygc?.periods?.[0]
    if (!latest) return []
    const byCategory = new Map<string, ZygcItem[]>()
    for (const item of latest.items) {
      const key = item.category || '其他'
      byCategory.set(key, [...(byCategory.get(key) || []), item])
    }
    return [...byCategory.entries()]
  }, [state.zygc])

  if (loading) {
    return <div className="flex h-64 items-center justify-center text-xs text-muted">加载经营数据…</div>
  }
  if (error) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-xs text-muted">
        <AlertTriangle className="h-5 w-5 text-warning" />
        <span>{error}</span>
        <span className="text-[10px]">AKShare 数据桥未启动?docker compose up -d akshare-bridge 后重试</span>
        <button
          type="button"
          onClick={() => setReloadKey(k => k + 1)}
          className="mt-1 inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] text-secondary hover:bg-elevated cursor-pointer"
        >
          <RefreshCw className="h-3 w-3" />重试
        </button>
      </div>
    )
  }

  const business = state.profile?.['主营业务']

  return (
    <div className="space-y-4">
      {/* 主营业务一句话 */}
      {business && (
        <section className="rounded border border-border/50 bg-base/30 p-3">
          <SectionTitle icon={Building2}>主营业务{state.peers?.industry ? ` · ${state.peers.industry}` : ''}</SectionTitle>
          <p className="mt-1.5 text-xs leading-relaxed text-secondary">{business}</p>
        </section>
      )}

      {/* 主营构成: 最新报告期, 按分类分组 */}
      {groups.length > 0 && (
        <section className="rounded border border-border/50 bg-base/30 p-3">
          <SectionTitle icon={Building2}>主营构成 · {state.zygc?.latest_date}</SectionTitle>
          {groups.map(([category, items]) => (
            <div key={category} className="mt-2.5">
              <div className="text-[10px] font-medium text-muted">{category}</div>
              <table className="mt-1 w-full text-[11px]">
                <thead>
                  <tr className="text-muted">
                    <th className="py-0.5 text-left font-normal">构成</th>
                    <th className="py-0.5 text-right font-normal">收入</th>
                    <th className="py-0.5 text-right font-normal">收入占比</th>
                    <th className="py-0.5 text-right font-normal">毛利率</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, i) => (
                    <tr key={`${item.name}-${i}`} className="border-t border-border/40">
                      <td className="py-1 text-foreground">{item.name}</td>
                      <td className="py-1 text-right font-mono text-secondary">{yi(item.revenue)}</td>
                      <td className="py-1 text-right font-mono text-secondary">{pct(item.revenue_ratio)}</td>
                      <td className={cn('py-1 text-right font-mono', (item.gross_margin ?? 0) >= 0.5 ? 'text-accent' : 'text-secondary')}>
                        {pct(item.gross_margin)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      )}

      {/* 同行清单 */}
      <section className="rounded border border-border/50 bg-base/30 p-3">
        <SectionTitle icon={Users}>同行{state.peers?.industry ? ` · ${state.peers.industry}` : ''}</SectionTitle>
        {state.peers?.peers?.length ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {state.peers.peers.slice(0, 20).map(p => (
              <span key={p.symbol} className="rounded bg-elevated/70 px-1.5 py-0.5 text-[11px] text-secondary">
                {p.name || p.symbol}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-1.5 text-[11px] text-muted">
            {state.peers?.degraded
              ? '上游板块成分接口暂不可用, 已降级为行业名; 可在 AI 助手中用行业名做横向对比'
              : '暂无同行数据'}
          </p>
        )}
      </section>
    </div>
  )
}
