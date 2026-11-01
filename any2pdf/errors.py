"""Stable error codes are stored independently of the selected UI language."""

MESSAGES = {
    'unsupported': ('不支持此文件格式。请选择支持列表中的文件。', 'This file format is not supported. Choose a supported format.'),
    'too_large': ('文件超过单文件 10 GiB 上限。', 'The file exceeds the 10 GiB per-file limit.'),
    'missing_file': ('文件不存在、已被移动，或不是普通文件。', 'The file is missing, has moved, or is not a regular file.'),
    'permission': ('没有读取文件或写入输出目录的权限。', 'Permission denied reading the source or writing the output directory.'),
    'disk_full': ('磁盘空间不足。请释放空间或更换输出目录。', 'Not enough disk space. Free some space or choose another output folder.'),
    'encrypted': ('文件受密码保护。请先解除加密后重试。', 'The file is password protected. Remove encryption before retrying.'),
    'invalid_pdf': ('文件损坏或不是有效的 PDF。', 'The file is damaged or is not a valid PDF.'),
    'invalid_image': ('图像损坏、解码失败或像素尺寸过大。', 'The image is damaged, cannot be decoded, or has excessive pixel dimensions.'),
    'text_encoding': ('无法识别文本编码，或文件并非文本。请另存为 UTF-8 后重试。', 'Text encoding is unsupported or the file is binary. Save it as UTF-8 and retry.'),
    'missing_office': ('未找到 LibreOffice 转换引擎。请使用包含引擎的完整便携包。', 'LibreOffice is missing. Use the full portable package with bundled engines.'),
    'missing_browser': ('未找到 Chromium 转换引擎。请使用包含引擎的完整便携包。', 'Chromium is missing. Use the full portable package with bundled engines.'),
    'engine_failed': ('转换引擎未能生成有效 PDF。文件可能损坏、受保护或含不支持的内容，请查看诊断详情。', 'The engine could not create a valid PDF. The file may be damaged, protected, or contain unsupported content. See diagnostics.'),
    'timeout': ('转换超时（单个任务最长 2 小时）。请拆分文件后重试。', 'Conversion timed out (2-hour limit per task). Split the file and retry.'),
    'cancelled': ('用户已取消转换。', 'Conversion cancelled by the user.'),
    'interrupted': ('上次运行意外结束，转换已中断。可重新添加或重试。', 'The previous session ended unexpectedly. Retry the interrupted task.'),
    'worker_crashed': ('转换进程异常退出，可能内存不足。请查看诊断详情。', 'The conversion process exited unexpectedly, possibly due to insufficient memory. See diagnostics.'),
    'unknown': ('转换失败，请查看诊断详情。', 'Conversion failed. See diagnostics for details.'),
}


class ConversionError(Exception):
    def __init__(self, code, detail=''):
        self.code = code
        self.detail = str(detail)[-16000:]
        super().__init__(f'{code}: {self.detail}')


def explain(code, lang='zh'):
    return MESSAGES.get(code, MESSAGES['unknown'])[lang == 'en']
