from PIL import Image

def letterbox(image, target_size=224):
    """保持宽高比缩放，灰色填充到正方形。

    Args:
        image: PIL.Image 对象
        target_size: 目标正方形边长

    Returns:
        PIL.Image 正方形图片
    """
    w, h = image.size
    scale = target_size / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    image = image.resize((new_w, new_h), Image.BILINEAR)

    canvas = Image.new("RGB", (target_size, target_size), (114, 114, 114))
    paste_x = (target_size - new_w) // 2
    paste_y = (target_size - new_h) // 2
    canvas.paste(image, (paste_x, paste_y))
    return canvas
