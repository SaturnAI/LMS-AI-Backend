class FileTypeNotSupported(Exception):
    """It is raised when unsupported file type is used by user"""


class FileSizeExceeded(Exception):
    """It is raised when file size exceeds the limit defined in config"""


class DataNotExtracted(Exception):
    """It is used when no data is extracted from file"""
