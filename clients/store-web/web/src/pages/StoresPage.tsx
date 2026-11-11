import { Link } from 'react-router-dom'

import { useStores } from '../api/queries'
import { Layout } from '../components/Layout'
import { StateBlock } from '../components/StateBlock'
import { formatCount } from '../lib/format'

export function StoresPage() {
  const stores = useStores()

  return (
    <Layout title="Cửa hàng">
      <div className="container">
        <p className="note">Chọn một cửa hàng để xem sản phẩm đang có tại đó.</p>

      {stores.isPending && <StateBlock kind="loading" title="Đang tải danh sách cửa hàng…" />}

      {stores.isError && (
        <StateBlock kind="error" error={stores.error} onRetry={() => void stores.refetch()} />
      )}

      {stores.isSuccess && stores.data.stores.length === 0 && (
        <StateBlock
          kind="empty"
          title="Chưa có cửa hàng nào đang hoạt động."
          message="Khi một cửa hàng được kích hoạt, nó sẽ hiện ở đây."
        />
      )}

      {stores.isSuccess && stores.data.stores.length > 0 && (
        <ul className="card-grid">
          {stores.data.stores.map((store) => (
            <li key={store.store_id}>
              <Link className="store-card" to={`/stores/${encodeURIComponent(store.store_id)}`}>
                <p className="store-card__name">{store.name}</p>
                <p className="store-card__meta">
                  {store.store_id} · Khu vực {store.region_id}
                </p>
                {store.address_text && <p className="store-card__address">{store.address_text}</p>}
                <p className="store-card__stats">
                  <span className="stat">
                    <span className="stat__label">Sản phẩm</span>
                    <span className="stat__value">{formatCount(store.product_count)} SKU</span>
                  </span>
                  <span className="stat">
                    <span className="stat__label">Còn bán được</span>
                    <span className="stat__value">
                      {formatCount(store.sellable_units)} đơn vị
                    </span>
                  </span>
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
      </div>
    </Layout>
  )
}
