"""
图像水印去除模块
基于颜色通道差异的水印去除功能

该模块提供了一个自动化的图像处理功能，专门用于去除文档图像中的彩色水印（尤其是红色印章）。
通过分析颜色通道的差异来识别水印区域，然后使用图像修复技术智能填充被去除的区域。

主要功能:
    - 自动检测和去除彩色水印
    - 保留图像的原始背景信息（文字、表格等）
    - 支持多种通道差异策略
    - 可配置的参数以适应不同的水印类型

作者: ideaBin
版本: V1.0
日期: 2025年10月22日
"""

import cv2
import numpy as np
from typing import Tuple, Literal
from enum import Enum


class ChannelStrategy(str, Enum):
    """通道减法策略枚举"""
    R_MINUS_B = "R-B"  # 针对红色水印
    B_MINUS_R = "B-R"  # 针对蓝色水印
    R_MINUS_G = "R-G"  # 针对红色水印（备用策略）
    G_MINUS_R = "G-R"  # 针对绿色水印


class InpaintAlgorithm(str, Enum):
    """图像修复算法枚举"""
    TELEA = "TELEA"  # 基于快速行进方法的修复算法
    NS = "NS"        # 基于Navier-Stokes的修复算法


class WatermarkRemover:
    """
    水印去除器类
    
    该类封装了基于颜色通道差异的水印去除功能，提供了灵活的参数配置
    和完整的图像处理流程。
    
    Attributes:
        channel_strategy: 通道减法策略
        threshold_value: 二值化阈值（0-255）
        morph_kernel_size: 形态学操作的核大小
        inpaint_algorithm: 图像修复算法
        inpaint_radius: 修复算法的邻域半径
    
    Example:
        >>> remover = WatermarkRemover(threshold_value=15)
        >>> result = remover.remove_watermark(image)
    """
    
    def __init__(
        self,
        channel_strategy: str = ChannelStrategy.R_MINUS_B,
        threshold_value: int = 10,
        morph_kernel_size: Tuple[int, int] = (5, 5),
        inpaint_algorithm: str = InpaintAlgorithm.TELEA,
        inpaint_radius: int = 3
    ):
        """
        初始化水印去除器
        
        Args:
            channel_strategy: 通道减法策略，可选值: 'R-B', 'B-R', 'R-G', 'G-R'
            threshold_value: 生成蒙版的亮度阈值（0-255），值越大检测越严格
            morph_kernel_size: 形态学闭运算的核大小，必须为奇数
            inpaint_algorithm: 图像修复算法，可选值: 'TELEA', 'NS'
            inpaint_radius: 修复算法参考的邻域半径
            
        Raises:
            ValueError: 当参数值无效时抛出
        """
        # 验证通道策略
        if channel_strategy not in [s.value for s in ChannelStrategy]:
            raise ValueError(
                f"无效的通道策略: {channel_strategy}. "
                f"可选值: {[s.value for s in ChannelStrategy]}"
            )
        self.channel_strategy = channel_strategy
        
        # 验证阈值
        if not (0 <= threshold_value <= 255):
            raise ValueError(f"阈值必须在0-255之间，当前值: {threshold_value}")
        self.threshold_value = threshold_value
        
        # 验证核大小
        if len(morph_kernel_size) != 2:
            raise ValueError(f"核大小必须是2元组，当前值: {morph_kernel_size}")
        if morph_kernel_size[0] % 2 == 0 or morph_kernel_size[1] % 2 == 0:
            raise ValueError(f"核大小必须为奇数，当前值: {morph_kernel_size}")
        if morph_kernel_size[0] < 1 or morph_kernel_size[1] < 1:
            raise ValueError(f"核大小必须大于0，当前值: {morph_kernel_size}")
        self.morph_kernel_size = morph_kernel_size
        
        # 验证修复算法
        if inpaint_algorithm not in [a.value for a in InpaintAlgorithm]:
            raise ValueError(
                f"无效的修复算法: {inpaint_algorithm}. "
                f"可选值: {[a.value for a in InpaintAlgorithm]}"
            )
        self.inpaint_algorithm = inpaint_algorithm
        
        # 验证修复半径
        if inpaint_radius < 1:
            raise ValueError(f"修复半径必须大于0，当前值: {inpaint_radius}")
        self.inpaint_radius = inpaint_radius
    
    def _separate_channels(self, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        分离BGR图像的三个颜色通道
        
        Args:
            image: BGR格式的输入图像
            
        Returns:
            包含B、G、R三个通道的元组
        """
        b, g, r = cv2.split(image)
        return b, g, r
    
    def _compute_channel_difference(
        self,
        b: np.ndarray,
        g: np.ndarray,
        r: np.ndarray
    ) -> np.ndarray:
        """
        根据选定的策略计算通道差异
        
        Args:
            b: 蓝色通道
            g: 绿色通道
            r: 红色通道
            
        Returns:
            通道差异图像
        """
        if self.channel_strategy == ChannelStrategy.R_MINUS_B:
            # 针对红色水印: R通道值高，B通道值低
            diff = cv2.subtract(r, b)
        elif self.channel_strategy == ChannelStrategy.B_MINUS_R:
            # 针对蓝色水印: B通道值高，R通道值低
            diff = cv2.subtract(b, r)
        elif self.channel_strategy == ChannelStrategy.R_MINUS_G:
            # 针对红色水印的备用策略
            diff = cv2.subtract(r, g)
        elif self.channel_strategy == ChannelStrategy.G_MINUS_R:
            # 针对绿色水印
            diff = cv2.subtract(g, r)
        else:
            raise ValueError(f"未实现的策略: {self.channel_strategy}")
        
        return diff
    
    def _generate_mask(self, diff: np.ndarray) -> np.ndarray:
        """
        基于通道差异生成二值化蒙版
        
        Args:
            diff: 通道差异图像
            
        Returns:
            二值化蒙版（0或255）
        """
        # 应用全局阈值
        _, mask = cv2.threshold(
            diff,
            self.threshold_value,
            255,
            cv2.THRESH_BINARY
        )
        return mask
    
    def _optimize_mask(self, mask: np.ndarray) -> np.ndarray:
        """
        优化蒙版：使用形态学闭运算填充孔洞和平滑边缘
        
        Args:
            mask: 原始二值化蒙版
            
        Returns:
            优化后的蒙版
        """
        # 创建结构元素
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            self.morph_kernel_size
        )
        
        # 执行闭运算（先膨胀后腐蚀）
        optimized_mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            kernel
        )
        
        return optimized_mask
    
    def _inpaint_image(
        self,
        image: np.ndarray,
        mask: np.ndarray
    ) -> np.ndarray:
        """
        使用蒙版修复图像
        
        Args:
            image: 原始输入图像
            mask: 水印区域蒙版
            
        Returns:
            修复后的图像
        """
        # 选择修复算法
        if self.inpaint_algorithm == InpaintAlgorithm.TELEA:
            method = cv2.INPAINT_TELEA
        else:  # NS
            method = cv2.INPAINT_NS
        
        # 执行图像修复
        result = cv2.inpaint(
            image,
            mask,
            self.inpaint_radius,
            method
        )
        
        return result
    
    def remove_watermark(
        self,
        image: np.ndarray,
        return_mask: bool = False
    ) -> np.ndarray | Tuple[np.ndarray, np.ndarray]:
        """
        去除图像中的彩色水印（主接口）
        
        这是该类的主要对外接口，执行完整的水印去除流程：
        1. 验证输入图像
        2. 分离颜色通道
        3. 计算通道差异
        4. 生成并优化蒙版
        5. 修复图像
        
        Args:
            image: 待处理的BGR格式彩色图像（numpy.ndarray）
            return_mask: 是否同时返回生成的蒙版（用于调试和可视化）
            
        Returns:
            如果return_mask为False: 返回去除水印后的图像
            如果return_mask为True: 返回(去除水印后的图像, 优化后的蒙版)的元组
            
        Raises:
            ValueError: 当输入不是有效的三通道彩色图像时
            
        Example:
            # >>> import cv2
            # >>> image = cv2.imread('document.jpg')
            # >>> remover = WatermarkRemover(threshold_value=15)
            # >>> result = remover.remove_watermark(image)
            # >>> cv2.imwrite('result.jpg', result)
        """
        # 验证输入
        if not isinstance(image, np.ndarray):
            raise ValueError("输入必须是numpy.ndarray类型")
        
        if len(image.shape) != 3 or image.shape[2] != 3:
            raise ValueError(
                f"输入必须是三通道彩色图像，当前形状: {image.shape}"
            )
        
        # 1. 分离颜色通道
        b, g, r = self._separate_channels(image)
        
        # 2. 计算通道差异
        diff = self._compute_channel_difference(b, g, r)
        
        # 3. 生成蒙版
        mask = self._generate_mask(diff)
        
        # 4. 优化蒙版
        optimized_mask = self._optimize_mask(mask)
        
        # 5. 修复图像
        result = self._inpaint_image(image, optimized_mask)
        
        if return_mask:
            return result, optimized_mask
        else:
            return result


def remove_watermark(
    image: np.ndarray,
    channel_strategy: str = "R-B",
    threshold_value: int = 10,
    morph_kernel_size: Tuple[int, int] = (5, 5),
    inpaint_algorithm: str = "TELEA",
    inpaint_radius: int = 3,
    return_mask: bool = False
) -> np.ndarray | Tuple[np.ndarray, np.ndarray]:
    """
    去除图像水印的便捷函数（函数式接口）
    
    这是一个便捷的函数式接口，内部创建WatermarkRemover实例并调用其方法。
    适合一次性处理单张图像的场景。
    
    Args:
        image: 待处理的BGR格式彩色图像
        channel_strategy: 通道减法策略，默认'R-B'（去除红色水印）
        threshold_value: 二值化阈值（0-255），默认10
        morph_kernel_size: 形态学操作核大小，默认(5, 5)
        inpaint_algorithm: 修复算法，默认'TELEA'
        inpaint_radius: 修复半径，默认3
        return_mask: 是否返回蒙版，默认False
        
    Returns:
        去除水印后的图像，或(图像, 蒙版)元组
        
    Example:
        # >>> import cv2
        # >>> from watermark_remover import remove_watermark
        # >>>
        # >>> image = cv2.imread('document.jpg')
        # >>> result = remove_watermark(image, threshold_value=15)
        # >>> cv2.imwrite('result.jpg', result)
    """
    remover = WatermarkRemover(
        channel_strategy=channel_strategy,
        threshold_value=threshold_value,
        morph_kernel_size=morph_kernel_size,
        inpaint_algorithm=inpaint_algorithm,
        inpaint_radius=inpaint_radius
    )
    
    return remover.remove_watermark(image, return_mask=return_mask)


if __name__ == "__main__":
    # 简单的命令行测试
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python watermark_remover.py <输入图像路径> [输出图像路径]")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "output_no_watermark.png"
    
    # 读取图像
    print(f"正在读取图像: {input_path}")
    image = cv2.imread(input_path)
    
    if image is None:
        print(f"错误: 无法读取图像 {input_path}")
        sys.exit(1)
    
    # 去除水印
    print("正在去除水印...")
    result, mask = remove_watermark(image, threshold_value=10, return_mask=True)
    
    # 保存结果
    print(f"正在保存结果: {output_path}")
    cv2.imwrite(output_path, result)
    
    # 保存蒙版（用于调试）
    mask_path = output_path.replace(".", "_mask.")
    cv2.imwrite(mask_path, mask)
    
    print(f"完成! 结果已保存到: {output_path}")
    print(f"蒙版已保存到: {mask_path}")