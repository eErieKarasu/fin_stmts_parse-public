"""PDF 页面渲染；文档和渲染目录的生命周期由 PDF 处理器管理。"""

import os
import fitz


class PDFPageRenderer:
    def render(
        self,
        doc: fitz.Document,
        page_num: int,
        temp_dir: str,
        page_number: int
    ) -> str:
        """
        将PDF页面转换为图像

        Args:
            doc: PDF文档对象
            page_num: 页面索引（从0开始）
            temp_dir: 临时目录
            page_number: 页面编号（从1开始，用于文件名）

        Returns:
            图像文件路径
        """
        page = doc[page_num]

        # 提高分辨率
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        # 保存临时图像
        image_path = os.path.join(temp_dir, f"page_{page_number:02d}.png")
        pix.save(image_path)
        pix = None

        return image_path
