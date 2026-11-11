import { Link, useParams, useSearchParams } from 'react-router-dom'

import { useCategories, useProducts, useStore } from '../api/queries'
import { FilterBar } from '../components/FilterBar'
import { Layout } from '../components/Layout'
import { Pagination } from '../components/Pagination'
import { ProductTable } from '../components/ProductTable'
import { StateBlock } from '../components/StateBlock'
import { parseFilters, serializeFilters, defaultFilters } from '../lib/filters'
import { formatCount } from '../lib/format'
import { useUserLocation } from '../lib/locationContext'

export function StorePage() {
  const { storeId = '' } = useParams()
  const [search, setSearch] = useSearchParams()
  const filters = parseFilters(search)
  const { location } = useUserLocation()

  const store = useStore(storeId)
  const categories = useCategories()
  const products = useProducts(storeId, filters, location.latitude, location.longitude)

  function apply(nextFilters: typeof filters) {
    setSearch(serializeFilters(nextFilters), { replace: true })
  }

  if (store.isError) {
    return (
      <Layout title="Không tìm thấy cửa hàng" breadcrumbs={[{ label: 'Cửa hàng', to: '/stores' }]}>
        <div className="container">
          <StateBlock
            kind="error"
            title="Không tìm thấy cửa hàng"
            message={`Cửa hàng "${storeId}" không tồn tại hoặc đã ngừng hoạt động.`}
            error={store.error}
            onRetry={() => void store.refetch()}
          />
          <p>
            <Link to="/stores">← Về danh sách cửa hàng</Link>
          </p>
        </div>
      </Layout>
    )
  }

  const title = store.isSuccess ? store.data.name : 'Đang tải cửa hàng…'

  return (
    <Layout
      title={title}
      breadcrumbs={[{ label: 'Cửa hàng', to: '/stores' }, { label: title }]}
      actions={
        store.isSuccess ? (
          <p className="note">
            {store.data.store_id} · Khu vực {store.data.region_id} ·{' '}
            {formatCount(store.data.product_count)} SKU ·{' '}
            {formatCount(store.data.sellable_units)} đơn vị bán được
            {store.data.expired_units > 0
              ? ` · ${formatCount(store.data.expired_units)} đơn vị hết hạn`
              : ''}
          </p>
        ) : null
      }
    >
      <div className="container">
        <FilterBar
          filters={filters}
          categories={categories.data?.categories ?? []}
          onChange={apply}
          onReset={() => apply(defaultFilters())}
        />

        {products.isPending && <StateBlock kind="loading" title="Đang tải sản phẩm…" />}

        {products.isError && (
          <StateBlock kind="error" error={products.error} onRetry={() => void products.refetch()} />
        )}

        {products.isSuccess && (
          <>
            <p aria-live="polite" className="note">
              {formatCount(products.data.total)} sản phẩm trong hệ thống ·{' '}
              {store.isSuccess
                ? `${formatCount(store.data.product_count)} sản phẩm cửa hàng này đang bán`
                : ''}
            </p>

            {products.data.items.length === 0 ? (
              <StateBlock
                kind="empty"
                title="Không có sản phẩm khớp bộ lọc."
                message="Thử xoá bớt điều kiện lọc hoặc tìm bằng từ khoá khác."
              />
            ) : (
              <>
                <ProductTable storeId={storeId} items={products.data.items} />
                <Pagination
                  total={products.data.total}
                  filters={filters}
                  shown={products.data.items.length}
                  onChange={(offset) => apply({ ...filters, offset })}
                />
              </>
            )}
          </>
        )}
      </div>
    </Layout>
  )
}
