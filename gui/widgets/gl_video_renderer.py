"""
OpenGL 视频渲染器 — GPU 加速的视频帧显示

使用 QOpenGLWidget + GLSL shader 实现：
- YUV420P 三平面纹理上传 + GPU 颜色转换 (BT.601)
- GPU 旋转 (正交角度 UV 映射 + 任意角度矩阵)
- GPU 缩放 (硬件纹理采样)
- Cropbox 线框绘制 (GL_LINES)

Qt 6 官方文档依据：
- QOpenGLWidget (https://doc.qt.io/qt-6/qopenglwidget.html)
- QOpenGLShaderProgram (https://doc.qt.io/qt-6/qopenglshaderprogram.html)
- QOpenGLTexture (https://doc.qt.io/qt-6/qopengltexture.html)

颜色转换依据：
- ITU-R BT.601 YCbCr → RGB 转换矩阵
"""
import logging
import ctypes
import math
from typing import Optional, Tuple

import numpy as np

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMatrix4x4

try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from PyQt6.QtOpenGL import (
        QOpenGLShaderProgram, QOpenGLShader,
    )
    HAS_OPENGL = True
except ImportError:
    HAS_OPENGL = False

# 模块级单次导入 PyOpenGL — 避免在13个方法中重复 from OpenGL import GL
# PyOpenGL 使用插件系统 (plugins.importByName) 动态加载 FormatHandler，
# cx_Freeze 无法跟踪 __import__ 字符串形式的动态导入，需要在 build.py includes 中显式声明
try:
    from OpenGL import GL as _GL
    HAS_PYOPENGL = True
except Exception:
    _GL = None
    HAS_PYOPENGL = False

logger = logging.getLogger(__name__)

# ── Shader 源码 ──

VERTEX_SHADER_SRC = """
#version 330 core
layout(location = 0) in vec2 a_position;
layout(location = 1) in vec2 a_texcoord;

uniform mat4 u_mvp;

out vec2 v_texcoord;

void main() {
    gl_Position = u_mvp * vec4(a_position, 0.0, 1.0);
    v_texcoord = a_texcoord;
}
"""

# YUV420P → RGB (BT.601 标准)
FRAGMENT_SHADER_YUV_SRC = """
#version 330 core
in vec2 v_texcoord;

uniform sampler2D tex_y;
uniform sampler2D tex_u;
uniform sampler2D tex_v;

out vec4 frag_color;

void main() {
    float y = texture(tex_y, v_texcoord).r;
    float u = texture(tex_u, v_texcoord).r - 0.5;
    float v = texture(tex_v, v_texcoord).r - 0.5;

    // BT.601 YCbCr -> RGB
    float r = y + 1.402 * v;
    float g = y - 0.344136 * u - 0.714136 * v;
    float b = y + 1.772 * u;

    frag_color = vec4(clamp(r, 0.0, 1.0),
                      clamp(g, 0.0, 1.0),
                      clamp(b, 0.0, 1.0), 1.0);
}
"""

# BGR/RGB 纹理直接显示
FRAGMENT_SHADER_RGB_SRC = """
#version 330 core
in vec2 v_texcoord;

uniform sampler2D tex_rgb;

out vec4 frag_color;

void main() {
    frag_color = texture(tex_rgb, v_texcoord);
}
"""

# Cropbox 纯色 shader
VERTEX_SHADER_CROPBOX_SRC = """
#version 330 core
layout(location = 0) in vec2 a_position;

uniform mat4 u_mvp;

void main() {
    gl_Position = u_mvp * vec4(a_position, 0.0, 1.0);
}
"""

FRAGMENT_SHADER_CROPBOX_SRC = """
#version 330 core
uniform vec4 u_color;

out vec4 frag_color;

void main() {
    frag_color = u_color;
}
"""

# 全屏四边形顶点 (position x,y + texcoord u,v)
QUAD_VERTICES = np.array([
    # position    texcoord
    -1.0, -1.0,   0.0, 1.0,   # 左下
     1.0, -1.0,   1.0, 1.0,   # 右下
    -1.0,  1.0,   0.0, 0.0,   # 左上
     1.0,  1.0,   1.0, 0.0,   # 右上
], dtype=np.float32)


def _check_opengl_available() -> bool:
    """检查 OpenGL 模块是否可用"""
    return HAS_OPENGL and HAS_PYOPENGL


class GLVideoWidget(QOpenGLWidget):
    """OpenGL 视频渲染器

    支持两种帧格式:
    - YUV420P: 三平面纹理，GPU shader 转 RGB (视频帧)
    - BGR/RGB: 单纹理直接显示 (静态图片)
    """

    def __init__(self, parent=None):
        if not HAS_OPENGL:
            raise RuntimeError("PyQt6 OpenGL 模块不可用")
        super().__init__(parent)

        # GL 状态
        self._gl_initialized: bool = False
        self._gl_failed: bool = False
        self._gl = None  # OpenGL functions

        # Shader programs
        self._yuv_program: Optional[QOpenGLShaderProgram] = None
        self._rgb_program: Optional[QOpenGLShaderProgram] = None
        self._cropbox_program: Optional[QOpenGLShaderProgram] = None

        # 纹理 ID (手动管理，避免 QOpenGLTexture 的复杂性)
        self._tex_y: int = 0
        self._tex_u: int = 0
        self._tex_v: int = 0
        self._tex_rgb: int = 0

        # 纹理尺寸
        self._tex_width: int = 0
        self._tex_height: int = 0

        # VBO/VAO
        self._quad_vbo: int = 0
        self._quad_vao: int = 0
        self._cropbox_vbo: int = 0
        self._cropbox_vao: int = 0

        # 帧数据 (主线程写入, paintGL 读取)
        self._yuv_data: Optional[Tuple[bytes, bytes, bytes, int, int]] = None
        self._rgb_data: Optional[Tuple[np.ndarray, int, int]] = None
        self._frame_dirty: bool = False
        self._use_yuv: bool = False

        # 渲染参数
        self._rotation_degrees: int = 0
        self._mvp_matrix = QMatrix4x4()
        self._mvp_matrix.setToIdentity()

        # Cropbox (旋转后视频坐标系)
        self._cropbox: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self._cropbox_rotated_w: int = 0
        self._cropbox_rotated_h: int = 0
        self._video_width: int = 0
        self._video_height: int = 0
        self._show_cropbox: bool = True

        # 显示参数 (用于坐标转换)
        self._display_rect: Tuple[int, int, int, int] = (0, 0, 1, 1)

        self.setMinimumSize(100, 100)

    @property
    def gl_failed(self) -> bool:
        return self._gl_failed

    # ── QOpenGLWidget 生命周期 ──

    def initializeGL(self):
        """初始化 OpenGL 资源"""
        if not HAS_PYOPENGL or _GL is None:
            logger.warning("PyOpenGL 不可用，跳过 GL 初始化")
            self._gl_failed = True
            return

        self._gl = _GL

        # 使用 PyQt6 内置的 OpenGL 函数
        ctx = self.context()
        if ctx is None or not ctx.isValid():
            logger.error("OpenGL 上下文无效")
            self._gl_failed = True
            return

        fmt = ctx.format()
        major, minor = fmt.majorVersion(), fmt.minorVersion()
        logger.info(f"OpenGL 版本: {major}.{minor}")

        if major < 3 or (major == 3 and minor < 3):
            logger.warning(
                f"OpenGL {major}.{minor} 版本过低，需要 3.3+")
            self._gl_failed = True
            return

        # 获取 OpenGL 函数
        try:
            from PyQt6.QtOpenGL import QOpenGLVersionFunctionsFactory
            from PyQt6.QtOpenGL import QOpenGLVersionProfile
            profile = QOpenGLVersionProfile()
            profile.setVersion(3, 3)
            profile.setProfile(
                fmt.CoreProfile if hasattr(fmt, 'CoreProfile')
                else 0)
            self._gl_funcs = (
                QOpenGLVersionFunctionsFactory.get(profile, ctx))
        except Exception:
            self._gl_funcs = None

        # 编译 shader
        if not self._compile_shaders():
            self._gl_failed = True
            return

        # 创建 VAO/VBO
        self._create_quad_buffers()
        if self._gl_failed:
            return
        self._create_cropbox_buffers()
        if self._gl_failed:
            return

        # 创建纹理
        self._create_textures()

        # GL 状态
        _GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        _GL.glDisable(__GL.GL_DEPTH_TEST)

        self._gl_initialized = True
        logger.info("GLVideoWidget OpenGL 初始化成功")

    def resizeGL(self, w: int, h: int):
        """窗口大小变化"""
        if self._gl_failed or _GL is None:
            return
        _GL.glViewport(0, 0, w, h)
        self._update_display_rect()

    def paintGL(self):
        """绘制帧"""
        if self._gl_failed or not self._gl_initialized or _GL is None:
            return

        _GL.glClear(__GL.GL_COLOR_BUFFER_BIT)

        # 上传新帧数据
        if self._frame_dirty:
            if self._use_yuv and self._yuv_data is not None:
                self._upload_yuv_textures()
            elif not self._use_yuv and self._rgb_data is not None:
                self._upload_rgb_texture()
            self._frame_dirty = False

        # 绘制视频帧
        if self._use_yuv and self._tex_y:
            self._draw_yuv_frame()
        elif not self._use_yuv and self._tex_rgb:
            self._draw_rgb_frame()

        # 绘制 cropbox
        if self._show_cropbox and self._video_width > 0:
            self._draw_cropbox()

    # ── 公共方法 ──

    def upload_yuv_frame(self, y_data: bytes, u_data: bytes,
                         v_data: bytes, width: int, height: int):
        """上传 YUV420P 帧 (主线程调用)"""
        self._yuv_data = (y_data, u_data, v_data, width, height)
        self._use_yuv = True
        self._video_width = width
        self._video_height = height
        self._frame_dirty = True
        self.update()

    def upload_bgr_frame(self, bgr_array: np.ndarray):
        """上传 BGR numpy 帧 (主线程调用，用于静态图片)"""
        # BGR → RGB 转换
        rgb = bgr_array[:, :, ::-1].copy()
        h, w = rgb.shape[:2]
        self._rgb_data = (rgb, w, h)
        self._use_yuv = False
        self._video_width = w
        self._video_height = h
        self._frame_dirty = True
        self.update()

    def upload_rgb_frame(self, rgb_array: np.ndarray):
        """上传 RGB numpy 帧 (主线程调用)"""
        h, w = rgb_array.shape[:2]
        self._rgb_data = (rgb_array.copy(), w, h)
        self._use_yuv = False
        self._video_width = w
        self._video_height = h
        self._frame_dirty = True
        self.update()

    def set_rotation(self, degrees: int):
        """设置旋转角度"""
        self._rotation_degrees = degrees % 360
        self._update_mvp()
        self._update_display_rect()
        self.update()

    def set_cropbox(self, x: int, y: int, w: int, h: int,
                    rotated_w: int = 0, rotated_h: int = 0):
        """设置 cropbox (旋转后视频坐标系)

        Args:
            x, y, w, h: cropbox 在旋转后视频坐标系中的位置
            rotated_w, rotated_h: 旋转后视频尺寸（用于 NDC 映射）
        """
        self._cropbox = (x, y, w, h)
        if rotated_w > 0 and rotated_h > 0:
            self._cropbox_rotated_w = rotated_w
            self._cropbox_rotated_h = rotated_h
        self.update()

    def set_show_cropbox(self, show: bool):
        """显示/隐藏 cropbox"""
        self._show_cropbox = show
        self.update()

    def widget_to_video_coords(self, wx: int, wy: int) -> Tuple[int, int]:
        """widget 像素坐标 → 视频像素坐标"""
        if self._video_width <= 0 or self._video_height <= 0:
            return (0, 0)

        rx, ry, rw, rh = self._display_rect
        if rw <= 0 or rh <= 0:
            return (0, 0)

        # widget → 归一化显示坐标 [0, 1]
        nx = (wx - rx) / rw
        ny = (wy - ry) / rh

        # 应用逆旋转
        vx, vy = self._apply_inverse_rotation(nx, ny)

        # 归一化 → 视频像素坐标
        px = int(vx * self._video_width)
        py = int(vy * self._video_height)
        return (max(0, min(px, self._video_width - 1)),
                max(0, min(py, self._video_height - 1)))

    def video_to_widget_coords(self, vx: int, vy: int) -> Tuple[int, int]:
        """视频像素坐标 → widget 像素坐标"""
        if self._video_width <= 0 or self._video_height <= 0:
            return (0, 0)

        rx, ry, rw, rh = self._display_rect
        if rw <= 0 or rh <= 0:
            return (0, 0)

        # 视频像素 → 归一化 [0, 1]
        nx = vx / self._video_width
        ny = vy / self._video_height

        # 应用旋转
        rnx, rny = self._apply_forward_rotation(nx, ny)

        # 归一化 → widget 像素
        wx = int(rnx * rw + rx)
        wy = int(rny * rh + ry)
        return (wx, wy)

    # ── 内部方法 ──

    def _compile_shaders(self) -> bool:
        """编译所有 shader 程序"""
        # YUV shader
        self._yuv_program = QOpenGLShaderProgram(self)
        if not self._yuv_program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SHADER_SRC):
            logger.error(f"YUV vertex shader 编译失败: "
                         f"{self._yuv_program.log()}")
            return False
        if not self._yuv_program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment,
                FRAGMENT_SHADER_YUV_SRC):
            logger.error(f"YUV fragment shader 编译失败: "
                         f"{self._yuv_program.log()}")
            return False
        if not self._yuv_program.link():
            logger.error(f"YUV shader 链接失败: "
                         f"{self._yuv_program.log()}")
            return False

        # RGB shader
        self._rgb_program = QOpenGLShaderProgram(self)
        if not self._rgb_program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SHADER_SRC):
            logger.error(f"RGB vertex shader 编译失败")
            return False
        if not self._rgb_program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment,
                FRAGMENT_SHADER_RGB_SRC):
            logger.error(f"RGB fragment shader 编译失败")
            return False
        if not self._rgb_program.link():
            logger.error(f"RGB shader 链接失败")
            return False

        # Cropbox shader
        self._cropbox_program = QOpenGLShaderProgram(self)
        if not self._cropbox_program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex,
                VERTEX_SHADER_CROPBOX_SRC):
            logger.error(f"Cropbox vertex shader 编译失败")
            return False
        if not self._cropbox_program.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment,
                FRAGMENT_SHADER_CROPBOX_SRC):
            logger.error(f"Cropbox fragment shader 编译失败")
            return False
        if not self._cropbox_program.link():
            logger.error(f"Cropbox shader 链接失败")
            return False

        logger.info("所有 shader 编译链接成功")
        return True

    def _create_quad_buffers(self):
        """创建全屏四边形 VAO/VBO"""
        self._quad_vao = _GL.glGenVertexArrays(1)
        self._quad_vbo = _GL.glGenBuffers(1)
        if not self._quad_vao or not self._quad_vbo:
            logger.error("glGenVertexArrays/glGenBuffers 失败 (quad)")
            self._gl_failed = True
            return

        _GL.glBindVertexArray(self._quad_vao)
        _GL.glBindBuffer(__GL.GL_ARRAY_BUFFER, self._quad_vbo)
        _GL.glBufferData(__GL.GL_ARRAY_BUFFER, QUAD_VERTICES.nbytes,
                         QUAD_VERTICES, __GL.GL_STATIC_DRAW)

        # position (location=0)
        _GL.glEnableVertexAttribArray(0)
        _GL.glVertexAttribPointer(
            0, 2, __GL.GL_FLOAT, __GL.GL_FALSE, 16,
            ctypes.c_void_p(0))
        # texcoord (location=1)
        _GL.glEnableVertexAttribArray(1)
        _GL.glVertexAttribPointer(
            1, 2, __GL.GL_FLOAT, __GL.GL_FALSE, 16,
            ctypes.c_void_p(8))

        _GL.glBindVertexArray(0)

    def _create_cropbox_buffers(self):
        """创建 cropbox 线框 VAO/VBO"""
        self._cropbox_vao = _GL.glGenVertexArrays(1)
        self._cropbox_vbo = _GL.glGenBuffers(1)
        if not self._cropbox_vao or not self._cropbox_vbo:
            logger.error("glGenVertexArrays/glGenBuffers 失败 (cropbox)")
            self._gl_failed = True
            return

        _GL.glBindVertexArray(self._cropbox_vao)
        _GL.glBindBuffer(__GL.GL_ARRAY_BUFFER, self._cropbox_vbo)
        # 预分配空间 (4 条边 + 4 个手柄 = 最多 40 个顶点)
        _GL.glBufferData(__GL.GL_ARRAY_BUFFER, 40 * 2 * 4,
                         None, __GL.GL_DYNAMIC_DRAW)

        _GL.glEnableVertexAttribArray(0)
        _GL.glVertexAttribPointer(
            0, 2, __GL.GL_FLOAT, __GL.GL_FALSE, 8,
            ctypes.c_void_p(0))

        _GL.glBindVertexArray(0)

    def _create_textures(self):
        """创建纹理对象"""
        # YUV 纹理
        self._tex_y = _GL.glGenTextures(1)
        self._tex_u = _GL.glGenTextures(1)
        self._tex_v = _GL.glGenTextures(1)

        for tex in [self._tex_y, self._tex_u, self._tex_v]:
            _GL.glBindTexture(__GL.GL_TEXTURE_2D, tex)
            _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                                __GL.GL_TEXTURE_MIN_FILTER, __GL.GL_LINEAR)
            _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                                __GL.GL_TEXTURE_MAG_FILTER, __GL.GL_LINEAR)
            _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                                __GL.GL_TEXTURE_WRAP_S, __GL.GL_CLAMP_TO_EDGE)
            _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                                __GL.GL_TEXTURE_WRAP_T, __GL.GL_CLAMP_TO_EDGE)

        # RGB 纹理
        self._tex_rgb = _GL.glGenTextures(1)
        _GL.glBindTexture(__GL.GL_TEXTURE_2D, self._tex_rgb)
        _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                            __GL.GL_TEXTURE_MIN_FILTER, __GL.GL_LINEAR)
        _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                            __GL.GL_TEXTURE_MAG_FILTER, __GL.GL_LINEAR)
        _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                            __GL.GL_TEXTURE_WRAP_S, __GL.GL_CLAMP_TO_EDGE)
        _GL.glTexParameteri(__GL.GL_TEXTURE_2D,
                            __GL.GL_TEXTURE_WRAP_T, __GL.GL_CLAMP_TO_EDGE)

        _GL.glBindTexture(__GL.GL_TEXTURE_2D, 0)

    def _upload_yuv_textures(self):
        """上传 YUV420P 帧数据到 GPU"""
        y_data, u_data, v_data, w, h = self._yuv_data
        need_recreate = (w != self._tex_width or h != self._tex_height)
        self._tex_width = w
        self._tex_height = h

        uw, uh = w // 2, h // 2

        # Y 平面
        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_y)
        if need_recreate:
            _GL.glTexImage2D(_GL.GL_TEXTURE_2D, 0, _GL.GL_R8,
                            w, h, 0, _GL.GL_RED, _GL.GL_UNSIGNED_BYTE,
                            y_data)
        else:
            _GL.glTexSubImage2D(_GL.GL_TEXTURE_2D, 0, 0, 0,
                               w, h, _GL.GL_RED, _GL.GL_UNSIGNED_BYTE,
                               y_data)

        # U 平面
        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_u)
        if need_recreate:
            _GL.glTexImage2D(_GL.GL_TEXTURE_2D, 0, _GL.GL_R8,
                            uw, uh, 0, _GL.GL_RED, _GL.GL_UNSIGNED_BYTE,
                            u_data)
        else:
            _GL.glTexSubImage2D(_GL.GL_TEXTURE_2D, 0, 0, 0,
                               uw, uh, _GL.GL_RED, _GL.GL_UNSIGNED_BYTE,
                               u_data)

        # V 平面
        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_v)
        if need_recreate:
            _GL.glTexImage2D(_GL.GL_TEXTURE_2D, 0, _GL.GL_R8,
                            uw, uh, 0, _GL.GL_RED, _GL.GL_UNSIGNED_BYTE,
                            v_data)
        else:
            _GL.glTexSubImage2D(_GL.GL_TEXTURE_2D, 0, 0, 0,
                               uw, uh, _GL.GL_RED, _GL.GL_UNSIGNED_BYTE,
                               v_data)

        _GL.glBindTexture(_GL.GL_TEXTURE_2D, 0)

    def _upload_rgb_texture(self):
        """上传 RGB 帧数据到 GPU"""
        rgb, w, h = self._rgb_data
        need_recreate = (w != self._tex_width or h != self._tex_height)
        self._tex_width = w
        self._tex_height = h

        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_rgb)
        _GL.glPixelStorei(_GL.GL_UNPACK_ALIGNMENT, 1)

        if need_recreate:
            _GL.glTexImage2D(_GL.GL_TEXTURE_2D, 0, _GL.GL_RGB8,
                            w, h, 0, _GL.GL_RGB, _GL.GL_UNSIGNED_BYTE,
                            rgb)
        else:
            _GL.glTexSubImage2D(_GL.GL_TEXTURE_2D, 0, 0, 0,
                               w, h, _GL.GL_RGB, _GL.GL_UNSIGNED_BYTE,
                               rgb)

        _GL.glBindTexture(_GL.GL_TEXTURE_2D, 0)

    def _draw_yuv_frame(self):
        """绘制 YUV 帧"""
        self._yuv_program.bind()

        # 设置 MVP 矩阵
        mvp_loc = self._yuv_program.uniformLocation("u_mvp")
        self._yuv_program.setUniformValue(mvp_loc, self._mvp_matrix)

        # 绑定 YUV 纹理
        _GL.glActiveTexture(_GL.GL_TEXTURE0)
        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_y)
        self._yuv_program.setUniformValue(
            self._yuv_program.uniformLocation("tex_y"), 0)

        _GL.glActiveTexture(_GL.GL_TEXTURE1)
        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_u)
        self._yuv_program.setUniformValue(
            self._yuv_program.uniformLocation("tex_u"), 1)

        _GL.glActiveTexture(_GL.GL_TEXTURE2)
        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_v)
        self._yuv_program.setUniformValue(
            self._yuv_program.uniformLocation("tex_v"), 2)

        # 绘制
        _GL.glBindVertexArray(self._quad_vao)
        _GL.glDrawArrays(_GL.GL_TRIANGLE_STRIP, 0, 4)
        _GL.glBindVertexArray(0)

        self._yuv_program.release()

    def _draw_rgb_frame(self):
        """绘制 RGB 帧"""
        self._rgb_program.bind()

        mvp_loc = self._rgb_program.uniformLocation("u_mvp")
        self._rgb_program.setUniformValue(mvp_loc, self._mvp_matrix)

        _GL.glActiveTexture(_GL.GL_TEXTURE0)
        _GL.glBindTexture(_GL.GL_TEXTURE_2D, self._tex_rgb)
        self._rgb_program.setUniformValue(
            self._rgb_program.uniformLocation("tex_rgb"), 0)

        _GL.glBindVertexArray(self._quad_vao)
        _GL.glDrawArrays(_GL.GL_TRIANGLE_STRIP, 0, 4)
        _GL.glBindVertexArray(0)

        self._rgb_program.release()

    def _draw_cropbox(self):
        """绘制 cropbox 线框和角落手柄（屏幕空间，不受旋转 MVP 影响）

        cropbox 坐标在旋转后视频坐标系中，映射到 display_rect 屏幕区域，
        然后转换为 NDC。使用 identity MVP 绘制。
        """
        cx, cy, cw, ch = self._cropbox
        if cw <= 0 or ch <= 0:
            return

        rot_w = self._cropbox_rotated_w
        rot_h = self._cropbox_rotated_h
        if rot_w <= 0 or rot_h <= 0:
            return

        ww, wh = self.width(), self.height()
        if ww <= 0 or wh <= 0:
            return

        dx, dy, dw, dh = self._display_rect
        if dw <= 0 or dh <= 0:
            return

        # 旋转后视频坐标 → 屏幕像素 → NDC
        def to_ndc(vx, vy):
            sx = dx + (vx / rot_w) * dw
            sy = dy + (vy / rot_h) * dh
            nx = (sx / ww) * 2.0 - 1.0
            ny = 1.0 - (sy / wh) * 2.0
            return nx, ny

        x1, y1 = to_ndc(cx, cy)
        x2, y2 = to_ndc(cx + cw, cy + ch)

        # 矩形边框 (4 条线段, 8 个顶点)
        line_vertices = np.array([
            x1, y1,  x2, y1,   # 上
            x2, y1,  x2, y2,   # 右
            x2, y2,  x1, y2,   # 下
            x1, y2,  x1, y1,   # 左
        ], dtype=np.float32)

        self._cropbox_program.bind()

        # 使用 identity MVP（cropbox 已在屏幕空间）
        identity = QMatrix4x4()
        mvp_loc = self._cropbox_program.uniformLocation("u_mvp")
        self._cropbox_program.setUniformValue(mvp_loc, identity)

        # 绘制绿色边框
        color_loc = self._cropbox_program.uniformLocation("u_color")
        self._cropbox_program.setUniformValue(
            color_loc, 0.0, 1.0, 0.0, 1.0)

        _GL.glBindVertexArray(self._cropbox_vao)
        _GL.glBindBuffer(_GL.GL_ARRAY_BUFFER, self._cropbox_vbo)
        _GL.glBufferSubData(_GL.GL_ARRAY_BUFFER, 0,
                           line_vertices.nbytes, line_vertices)

        _GL.glLineWidth(2.0)
        _GL.glDrawArrays(_GL.GL_LINES, 0, 8)

        # 绘制角落手柄 (4 个小正方形)
        hs_x = 8.0 / ww * 2.0
        hs_y = 8.0 / wh * 2.0

        handle_verts = []
        for hx, hy in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
            handle_verts.extend([
                hx - hs_x, hy - hs_y,
                hx + hs_x, hy - hs_y,
                hx - hs_x, hy + hs_y,
                hx + hs_x, hy - hs_y,
                hx + hs_x, hy + hs_y,
                hx - hs_x, hy + hs_y,
            ])

        handle_array = np.array(handle_verts, dtype=np.float32)

        # 青色手柄
        self._cropbox_program.setUniformValue(
            color_loc, 0.0, 0.78, 1.0, 1.0)

        _GL.glBufferSubData(_GL.GL_ARRAY_BUFFER, 0,
                           handle_array.nbytes, handle_array)
        _GL.glDrawArrays(_GL.GL_TRIANGLES, 0, 24)

        _GL.glBindVertexArray(0)
        self._cropbox_program.release()

    def _update_mvp(self):
        """更新 MVP 矩阵（含旋转和宽高比校正）"""
        self._mvp_matrix = QMatrix4x4()
        self._mvp_matrix.setToIdentity()

        deg = self._rotation_degrees
        if deg == 0:
            return

        # 对正交角度，通过纹理坐标处理更高效
        # 但为了统一处理，这里用矩阵旋转
        # 旋转
        self._mvp_matrix.rotate(-deg, 0.0, 0.0, 1.0)

        # 对 90/270 度，需要交换宽高比
        if deg in (90, 270) and self._video_width > 0 and self._video_height > 0:
            aspect = self._video_width / self._video_height
            widget_aspect = self.width() / max(self.height(), 1)
            # 旋转后视频宽高比反转
            if widget_aspect > 0:
                scale = min(1.0, 1.0 / aspect) if aspect > 1 else min(1.0, aspect)
                self._mvp_matrix.scale(
                    self._video_height / self._video_width,
                    self._video_width / self._video_height,
                    1.0)

        # 任意角度需要缩放以适应视口
        if deg not in (0, 90, 180, 270):
            rad = math.radians(deg)
            cos_a = abs(math.cos(rad))
            sin_a = abs(math.sin(rad))
            scale = 1.0 / (cos_a + sin_a)
            self._mvp_matrix.scale(scale, scale, 1.0)

    def _update_display_rect(self):
        """更新视频在 widget 内的显示区域（用于坐标转换）"""
        ww, wh = self.width(), self.height()
        vw, vh = self._video_width, self._video_height

        if vw <= 0 or vh <= 0 or ww <= 0 or wh <= 0:
            self._display_rect = (0, 0, ww, wh)
            return

        # 考虑旋转后的视频尺寸
        deg = self._rotation_degrees
        if deg in (90, 270):
            vw, vh = vh, vw

        # 等比缩放适应 widget
        scale = min(ww / vw, wh / vh)
        dw = int(vw * scale)
        dh = int(vh * scale)
        dx = (ww - dw) // 2
        dy = (wh - dh) // 2

        self._display_rect = (dx, dy, dw, dh)

    def _apply_inverse_rotation(self, nx: float, ny: float
                                ) -> Tuple[float, float]:
        """应用逆旋转 (widget 归一化坐标 → 视频归一化坐标)"""
        deg = self._rotation_degrees
        if deg == 0:
            return (nx, ny)
        elif deg == 90:
            return (ny, 1.0 - nx)
        elif deg == 180:
            return (1.0 - nx, 1.0 - ny)
        elif deg == 270:
            return (1.0 - ny, nx)
        else:
            # 任意角度逆旋转
            rad = math.radians(deg)
            cx, cy = 0.5, 0.5
            dx, dy = nx - cx, ny - cy
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            ux = dx * cos_a + dy * sin_a + cx
            uy = -dx * sin_a + dy * cos_a + cy
            return (ux, uy)

    def _apply_forward_rotation(self, nx: float, ny: float
                                ) -> Tuple[float, float]:
        """应用正向旋转 (视频归一化坐标 → widget 归一化坐标)"""
        deg = self._rotation_degrees
        if deg == 0:
            return (nx, ny)
        elif deg == 90:
            return (1.0 - ny, nx)
        elif deg == 180:
            return (1.0 - nx, 1.0 - ny)
        elif deg == 270:
            return (ny, 1.0 - nx)
        else:
            rad = math.radians(-deg)
            cx, cy = 0.5, 0.5
            dx, dy = nx - cx, ny - cy
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            ux = dx * cos_a + dy * sin_a + cx
            uy = -dx * sin_a + dy * cos_a + cy
            return (ux, uy)

    def cleanup(self):
        """清理 OpenGL 资源"""
        if not self._gl_initialized:
            return
        self.makeCurrent()
        try:
            if _GL is None:
                return
            if self._tex_y:
                _GL.glDeleteTextures([self._tex_y, self._tex_u,
                                     self._tex_v, self._tex_rgb])
            if self._quad_vbo:
                _GL.glDeleteBuffers(1, [self._quad_vbo])
            if self._quad_vao:
                _GL.glDeleteVertexArrays(1, [self._quad_vao])
            if self._cropbox_vbo:
                _GL.glDeleteBuffers(1, [self._cropbox_vbo])
            if self._cropbox_vao:
                _GL.glDeleteVertexArrays(1, [self._cropbox_vao])
        except Exception:
            pass
        self.doneCurrent()
        self._gl_initialized = False
