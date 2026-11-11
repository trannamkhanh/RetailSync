import type { Batch } from '../api/types'
import { formatDate } from '../lib/format'

interface BatchTableProps {
  batches: Batch[]
}

/**
 * Batch list of one product. The ``sellable`` flag comes from the API; the web
 * never compares expiry dates itself, because the viewer's clock and time zone
 * would change the answer.
 */
export function BatchTable({ batches }: BatchTableProps) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Các lô hàng của sản phẩm tại cửa hàng này</caption>
        <thead>
          <tr>
            <th scope="col">Mã lô</th>
            <th scope="col">Hạn dùng</th>
            <th scope="col" className="num">
              Số lượng
            </th>
            <th scope="col">Trạng thái</th>
          </tr>
        </thead>
        <tbody>
          {batches.map((batch) => (
            <tr key={batch.batch_id} className={batch.sellable ? undefined : 'expired'}>
              <td>{batch.batch_id}</td>
              <td>{formatDate(batch.expiry_date)}</td>
              <td className="num">{batch.quantity}</td>
              <td>
                {batch.sellable ? (
                  <span className="badge">còn bán</span>
                ) : (
                  <span className="badge badge--warn">hết hạn</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
