import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCategories, useShopSearch } from '../api/queries'
import { Layout } from '../components/Layout'
import { ProductImage } from '../components/ProductImage'
import { StateBlock } from '../components/StateBlock'
import { formatDistance, formatMoney } from '../lib/format'
import { useUserLocation } from '../lib/locationContext'

export function HomePage() {
  const { location } = useUserLocation()
  const [searchInput, setSearchInput] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('')

  const categories = useCategories()

  // Default query fetches popular products (or all items via general term like empty or space)
  const queryTerm = searchInput.trim() || ' '
  const searchResults = useShopSearch(
    queryTerm,
    location.latitude,
    location.longitude,
    selectedCategory,
  )

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    // The search input updates the queryTerm reactively
  }

  return (
    <Layout>
      <div className="container">
        {/* Hero Section with Search Banner */}
        <section className="hero-box">
          <h1 className="hero-title">Tìm hàng hoá gần bạn nhất</h1>
          <p className="hero-subtitle">
            Hệ thống tự động quét tồn kho thời gian thực tại các cửa hàng xung quanh toạ độ của bạn và
            chỉ điểm nơi còn sẵn hàng gần nhất!
          </p>

          <form className="hero-search-form" onSubmit={handleSearchSubmit}>
            <input
              type="text"
              className="hero-search-input"
              placeholder="Bạn đang tìm gì? (Vd: Sữa tươi, bánh mì, gạo, dầu ăn...)"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
            <button type="submit" className="btn btn-primary" style={{ borderRadius: 'var(--radius-full)' }}>
              🔍 Tìm kiếm
            </button>
          </form>
        </section>

        {/* Categories Bar */}
        <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 12, marginBottom: 20 }}>
          <button
            type="button"
            className={`btn btn-sm ${selectedCategory === '' ? 'btn-primary' : ''}`}
            onClick={() => setSelectedCategory('')}
          >
            Tất cả danh mục
          </button>
          {categories.data?.categories.map((cat) => (
            <button
              key={cat}
              type="button"
              className={`btn btn-sm ${selectedCategory === cat ? 'btn-primary' : ''}`}
              onClick={() => setSelectedCategory(cat)}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Search Results / Products Grid */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>
              {searchInput.trim() ? `Kết quả tìm kiếm cho "${searchInput}"` : 'Sản phẩm nổi bật'}
            </h2>
            <span style={{ fontSize: 13, color: 'var(--note)' }}>
              Toạ độ mua sắm: <strong>{location.label}</strong>
            </span>
          </div>

          {searchResults.isPending && (
            <StateBlock kind="loading" title="Đang dò tìm kho hàng gần bạn…" />
          )}

          {searchResults.isError && (
            <StateBlock
              kind="error"
              error={searchResults.error}
              onRetry={() => void searchResults.refetch()}
            />
          )}

          {searchResults.isSuccess && searchResults.data.items.length === 0 && (
            <StateBlock
              kind="empty"
              title="Không tìm thấy món hàng phù hợp."
              message="Hãy thử tìm bằng từ khoá khác hoặc đổi danh mục."
            />
          )}

          {searchResults.isSuccess && searchResults.data.items.length > 0 && (
            <div className="product-grid">
              {searchResults.data.items.map((prod) => (
                <div key={prod.sku} className="product-card">
                  <ProductImage src={prod.image_url} name={prod.name} />
                  <div className="product-category">{prod.category}</div>
                  <h3 className="product-name">{prod.name}</h3>
                  <div className="product-price">{formatMoney(prod.unit_price)}</div>

                  {/* Suggestion block pointing to nearest shop with stock */}
                  <div className="suggestion-box">
                    {prod.nearest ? (
                      <>
                        <div className="suggestion-header">
                          <span>📍 GỢI Ý CỬA HÀNG GẦN NHẤT</span>
                          <span style={{ fontSize: 11 }}>
                            {formatDistance(prod.nearest.distance_km, prod.nearest.distance_kind)}
                          </span>
                        </div>
                        <div className="store-name">{prod.nearest.name}</div>
                        {prod.nearest.address_text && (
                          <div className="store-address">{prod.nearest.address_text}</div>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                          <span className="store-stock">Còn {prod.nearest.sellable_quantity} sản phẩm</span>
                          <Link
                            to={`/stores/${prod.nearest.store_id}/products/${prod.sku}`}
                            style={{ fontSize: 12, fontWeight: 700, color: 'var(--primary-hover)' }}
                          >
                            Xem kho hàng →
                          </Link>
                        </div>
                      </>
                    ) : (
                      <div style={{ color: 'var(--danger)', fontSize: 13, fontWeight: 600 }}>
                        Tạm hết hàng ở tất cả các cửa hàng lân cận
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
