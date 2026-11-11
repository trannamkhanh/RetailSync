import { Link } from 'react-router-dom'

import { Layout } from '../components/Layout'

export function NotFoundPage() {
  return (
    <Layout title="Không tìm thấy trang">
      <div className="container">
        <p className="note">Đường dẫn này không tồn tại trong ứng dụng.</p>
        <p>
          <Link to="/stores">← Về danh sách cửa hàng</Link>
        </p>
      </div>
    </Layout>
  )
}
