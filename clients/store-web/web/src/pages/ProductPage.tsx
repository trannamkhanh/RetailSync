import { Link, useParams, useSearchParams } from 'react-router-dom'

import { useProduct, useStore } from '../api/queries'
import { BatchTable } from '../components/BatchTable'
import { Layout } from '../components/Layout'
import { ProductImage } from '../components/ProductImage'
import { StateBlock } from '../components/StateBlock'
import { formatCount, formatDate, formatMoney } from '../lib/format'

export function ProductPage() {
  const { storeId = '', sku = '' } = useParams()
  const [search, setSearch] = useSearchParams()
  const includeEmpty = search.get('include_empty') === 'true'

  const store = useStore(storeId)
  const product = useProduct(storeId, sku, includeEmpty)

  const storeName = store.data?.name ?? storeId
  const productName = product.data?.item.name ?? sku

  return (
    <Layout
      title={product.isSuccess ? productName : 'Đang tải sản phẩm…'}
      breadcrumbs={[
        { label: 'Cửa hàng', to: '/stores' },
        { label: storeName, to: `/stores/${encodeURIComponent(storeId)}` },
        { label: product.isSuccess ? productName : sku },
      ]}
    >
      <div className="container">
        <p className="note">
          <Link to={`/stores/${encodeURIComponent(storeId)}`}>← Về {storeName}</Link>
        </p>

        {product.isPending && <StateBlock kind="loading" title="Đang tải sản phẩm…" />}

        {product.isError && (
          <>
            <StateBlock
              kind="error"
              title="Không tìm thấy sản phẩm"
              message={`Sản phẩm "${sku}" không có trong danh mục của cửa hàng này.`}
              error={product.error}
              onRetry={() => void product.refetch()}
            />
            <p>
              <Link to={`/stores/${encodeURIComponent(storeId)}`}>← Về {storeName}</Link>
            </p>
          </>
        )}

        {product.isSuccess && (
          <>
            <section className="detail-card" aria-label="Thông tin sản phẩm">
              <div className="detail-card__body">
                <ProductImage src={product.data.item.image_url} name={product.data.item.name} size="card" />
                <dl>
                <dt>SKU</dt>
                <dd>{product.data.item.sku}</dd>
                <dt>Mã vạch</dt>
                <dd>{product.data.item.barcode}</dd>
                <dt>Danh mục</dt>
                <dd>{product.data.item.category}</dd>
                <dt>Giá</dt>
                <dd>{formatMoney(product.data.item.unit_price)}</dd>
                <dt>Còn bán</dt>
                <dd>
                  {formatCount(product.data.item.sellable_quantity)}
                  {product.data.item.sellable_quantity === 0 && (
                    <>
                      {' '}
                      <span className="badge badge--out">hết hàng</span>
                    </>
                  )}
                </dd>
                <dt>Tổng tồn</dt>
                <dd>
                  {formatCount(product.data.item.quantity)}
                  {product.data.item.expired_quantity > 0 && (
                    <> (gồm {formatCount(product.data.item.expired_quantity)} đơn vị hết hạn)</>
                  )}
                </dd>
                <dt>Sắp hết hạn</dt>
                <dd>{formatDate(product.data.item.nearest_expiry)}</dd>
                </dl>
              </div>
            </section>

            <h2>Lô hàng tại cửa hàng</h2>

            <p>
              <label>
                <input
                  type="checkbox"
                  checked={includeEmpty}
                  onChange={(event) => {
                    const next = new URLSearchParams(search)
                    if (event.target.checked) next.set('include_empty', 'true')
                    else next.delete('include_empty')
                    setSearch(next, { replace: true })
                  }}
                />{' '}
                Hiện cả lô đã hết số lượng
              </label>
            </p>

            {product.data.item.batches.length === 0 ? (
              <StateBlock
                kind="empty"
                title="Chưa có lô hàng nào."
                message="Sản phẩm này chưa được nhập kho tại cửa hàng."
              />
            ) : (
              <BatchTable batches={product.data.item.batches} />
            )}
          </>
        )}
      </div>
    </Layout>
  )
}
