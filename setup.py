"""Legacy setuptools configuration for Offline AI Assistant."""

from setuptools import find_packages, setup


INSTALL_REQUIRES = [
    "PySide6>=6.6",
    "llama-cpp-python>=0.3.0",
    "scipy>=1.13.0",
    "pyttsx3>=2.91",
    "psutil>=5.9.0",
    "sounddevice>=0.5.0",
    "faster-whisper>=1.0.0",
    "nvidia-ml-py3>=12.465.0; platform_system == 'Windows'",
    "requests>=2.31.0",
    "pywin32>=306; platform_system == 'Windows'",
]

EXTRAS_REQUIRE = {
    "voice": ["openwakeword>=0.6"],
    "vector": [
        "faiss-cpu>=1.8; platform_system == 'Windows'",
        "sentence-transformers>=2.7",
    ],
    "scheduler": ["croniter>=2.0"],
    "docs": [
        "pypdf>=3.9",
        "PyMuPDF>=1.24",
        "python-docx>=1.1",
        "docx2txt>=0.8",
        "beautifulsoup4>=4.12",
    ],
    "dev": [
        "pytest>=8.0",
        "pytest-qt>=4.4",
        "ruff>=0.4",
        "mypy>=1.10",
        "pyinstaller>=6.0",
    ],
}

EXTRAS_REQUIRE["full"] = [
    requirement
    for extra_name, requirements in EXTRAS_REQUIRE.items()
    if extra_name != "dev"
    for requirement in requirements
]

setup(
    name="OfflineAIAssistantFinal",
    version="3.1.0",
    description="Offline AI Assistant - final standalone application",
    author="OfflineAI Team",
    license="MIT",
    python_requires=">=3.11",
    packages=find_packages(),
    include_package_data=True,
    install_requires=INSTALL_REQUIRES,
    extras_require=EXTRAS_REQUIRE,
    entry_points={
        "console_scripts": [
            "offline-ai-final=app.application_final:main",
        ],
    },
)
