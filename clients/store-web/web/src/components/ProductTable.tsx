import { Link } from 'react-router-dom'

import type { Product } from '../api/types'
import { formatDate, formatDistance, formatMoney } from '../lib/format'
import { ProductImage } from './ProductImage'

interface ProductTableProps {
  storeId: string
  items: Product[]
}

/**
 * The product table. "Còn bán" is ``sellable_quantity``, never ``quantity``: the
 * inventory figure includes stock that has already expired.
 *
 * "Gần nhất còn hàng" tells the customer where to actually go. The API puts the
 * store being viewed first when it has the product, so a row reads either
 * "here" or the nearest branch that still has it.
 */
export function ProductTable({ storeId, items }: ProductTableProps) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">
          Sản phẩm tại cửa hàng {storeId}: tên, SKU, danh mục, giá, số lượng còn bán, hạn dùng
          gần nhất và cửa hàng gần nhất còn hàng
        </caption>
        <thead>
          <tr>
            <th scope="col">Tên</th>
            <th scope="col">SKU</th>
            <th scope="col">Danh mục</th>
            <th scope="col" className="num">
              Giá
            </th>
            <th scope="col" className="num">
              Còn bán
            </th>
            <th scope="col">Hạn gần nhất</th>
            <th scope="col">Gần nhất còn hàng</th>
          </tr>
        </thead>
        <tbody>
          {items.map((product) => (
            <tr key={product.sku}>
              <td>
                <span className="product-cell">
                  <ProductImage src={product.image_url} name={product.name} size="thumb" />
                  <Link to={`/stores/${encodeURIComponent(storeId)}/products/${encodeURIComponent(product.sku)}`}>
                    {product.name}
                  </Link>
                </span>
              </td>
              <td>{product.sku}</td>
              <td>{product.category}</td>
              <td className="num">{formatMoney(product.unit_price)}</td>
              <td className="num">
                {product.sellable_quantity > 0 ? (
                  product.sellable_quantity
                ) : (
                  <span className="badge badge--out">hết hàng</span>
                )}
              </td>
              <td>{formatDate(product.nearest_expiry)}</td>
              <td>
                {product.nearest_store ? (
                  <span className="nearest">
                    {product.nearest_store.store_id === storeId ? (
                      <span className="nearest__here">tại đây</span>
                    ) : (
                      <Link
                        className="nearest__link"
                        to={`/stores/${encodeURIComponent(product.nearest_store.store_id)}/products/${encodeURIComponent(product.sku)}`}
                      >
                        {product.nearest_store.name}
                      </Link>
                    )}
                    <span className="nearest__distance">
                      {product.nearest_store.store_id === storeId
                        ? ''
                        : formatDistance(
                            product.nearest_store.distance_km,
                            product.nearest_store.distance_kind,
                          )}
                    </span>
                  </span>
                ) : (
                  <span className="nearest__none">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
