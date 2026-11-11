const VND = new Intl.NumberFormat('vi-VN', {
  style: 'currency',
  currency: 'VND',
  maximumFractionDigits: 0,
})

/** `"32000.00"` → `32.000 ₫`. Never parsed as a float for arithmetic. */
export function formatMoney(unitPrice: string): string {
  const whole = unitPrice.split('.')[0] ?? unitPrice
  const digits = whole.replace(/[^\d-]/g, '')
  const value = Number(digits)
  if (!Number.isFinite(value)) return unitPrice
  return VND.format(value)
}

/** `"2026-11-13"` → `13/11/2026`; `null` → `—`. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [year, month, day] = iso.split('-')
  if (!year || !month || !day) return iso
  return `${day}/${month}/${year}`
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat('vi-VN').format(value)
}

/**
 * Distance for the shop suggestion. Under 100 m reads "ngay đây", not "0 km",
 * because the API rounds to 100 m and a zero looks like a bug.
 *
 * ``kind`` says how the API measured it: ``road`` is the driving distance from
 * the routing server, ``straight`` is the fallback straight line. The two are
 * not comparable, so the fallback is marked instead of shown as a road figure.
 */
export function formatDistance(km: number, kind: 'road' | 'straight' = 'road'): string {
  if (!Number.isFinite(km)) return '—'
  const text =
    km < 0.1
      ? 'ngay đây'
      : `${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(km)} km`
  return kind === 'straight' ? `${text} (đường chim bay)` : text
}
