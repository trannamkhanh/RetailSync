import { useState } from 'react'

interface ProductImageProps {
  src: string | null | undefined
  name: string
  /** `card` is the shop grid, `thumb` is the table row. */
  size?: 'card' | 'thumb'
}

/**
 * A product picture with a placeholder.
 *
 * The API gives a URL, not an image, so the file can be missing: an unmigrated
 * database, a SKU added without a picture, or a stale build. On error the image is
 * replaced by the product's first letter, so a broken file never shows a broken
 * image icon or collapses the layout.
 */
export function ProductImage({ src, name, size = 'card' }: ProductImageProps) {
  const [broken, setBroken] = useState(false)
  const className = `product-image product-image--${size}`
  const initial = name.trim().charAt(0).toUpperCase()

  if (!src || broken) {
    return (
      <div className={`${className} product-image--placeholder`} aria-hidden="true">
        {initial || '?'}
      </div>
    )
  }

  return (
    <img
      className={className}
      src={src}
      alt={name}
      loading="lazy"
      onError={() => setBroken(true)}
    />
  )
}
