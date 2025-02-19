import os

import torch
from setuptools import setup
from torch.utils.cpp_extension import BuildExtension, CUDAExtension

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# Find version of tinycudann by scraping CMakeLists.txt
with open(os.path.join(ROOT_DIR, "CMakeLists.txt"), "r") as cmakelists:
	for line in cmakelists.readlines():
		if line.strip().startswith("VERSION"):
			VERSION = line.split("VERSION")[-1].strip()
			break

print(f"Building PyTorch extension for tiny-cuda-nn version {VERSION}")

ext_modules = []

if torch.cuda.is_available():
	if os.name == "nt":
		def find_cl_path():
			import glob
			for edition in ["Enterprise", "Professional", "BuildTools", "Community"]:
				paths = sorted(glob.glob(r"C:\\Program Files (x86)\\Microsoft Visual Studio\\*\\%s\\VC\\Tools\\MSVC\\*\\bin\\Hostx64\\x64" % edition), reverse=True)
				if paths:
					return paths[0]

		# If cl.exe is not on path, try to find it.
		if os.system("where cl.exe >nul 2>nul") != 0:
			cl_path = find_cl_path()
			if cl_path is None:
				raise RuntimeError("Could not locate a supported Microsoft Visual C++ installation")
			os.environ["PATH"] += ";" + cl_path

	nvcc_flags = [
		"-std=c++14",
		"--extended-lambda",
		"--expt-relaxed-constexpr",
		# The following definitions must be undefined
		# since TCNN requires half-precision operation.
		"-U__CUDA_NO_HALF_OPERATORS__",
		"-U__CUDA_NO_HALF_CONVERSIONS__",
		"-U__CUDA_NO_HALF2_OPERATORS__",
	]
	if os.name == "posix":
		cflags = ["-std=c++14"]
		nvcc_flags += [
			"-Xcompiler=-mf16c",
			"-Xcompiler=-Wno-float-conversion",
			"-Xcompiler=-fno-strict-aliasing",
		]
	elif os.name == "nt":
		cflags = ["/std:c++14"]

	major, minor = torch.cuda.get_device_capability()
	compute_capability = major * 10 + minor

	print(f"Targeting compute capability {compute_capability}")

	definitions = [f"-DTCNN_MIN_GPU_ARCH={compute_capability}"]
	nvcc_flags += definitions
	cflags += definitions

	# Some containers set this to contain old architectures that won't compile. We only need the one installed in the machine.
	os.environ["TORCH_CUDA_ARCH_LIST"] = ""

	# List of sources.
	bindings_dir = os.path.dirname(__file__)
	root_dir = os.path.abspath(os.path.join(bindings_dir, "../.."))
	source_files = [
		"tinycudann/torch_bindings.cpp",
		"../../src/cpp_api.cu",
		"../../src/common.cu",
		"../../src/common_device.cu",
		"../../src/encoding.cu",
		"../../src/network.cu",
		"../../src/fully_fused_mlp.cu",
		"../../src/cutlass_mlp.cu",
		"../../src/cutlass_resnet.cu"
	]

	ext = CUDAExtension(
		name="tinycudann_bindings._C",
		sources=source_files,
		include_dirs=["%s/include" % root_dir, "%s/dependencies" % root_dir],
		extra_compile_args={"cxx": cflags, "nvcc": nvcc_flags},
		libraries=["cuda", "cudadevrt", "cudart_static"],
	)
	ext_modules = [ext]
else:
	raise EnvironmentError("PyTorch CUDA is unavailable. tinycudann requires PyTorch to be installed with the CUDA backend.")

setup(
	name="tinycudann",
	version=VERSION,
	description="tiny-cuda-nn extension for PyTorch",
	long_description="tiny-cuda-nn extension for PyTorch",
	classifiers=[
		"Development Status :: 4 - Beta",
		"Environment :: GPU :: NVIDIA CUDA",
		"License :: BSD 3-Clause",
		"Programming Language :: C++",
		"Programming Language :: CUDA",
		"Programming Language :: Python :: 3 :: Only",
		"Topic :: Multimedia :: Graphics",
		"Topic :: Scientific/Engineering :: Artificial Intelligence",
		"Topic :: Scientific/Engineering :: Image Processing",

	],
	keywords="PyTorch,cutlass,machine learning",
	url="https://github.com/nvlabs/tiny-cuda-nn",
	author="Thomas Müller, Jacob Munkberg, Jon Hasselgren, Or Perel",
	author_email="tmueller@nvidia.com, jmunkberg@nvidia.com, jhasselgren@nvidia.com, operel@nvidia.com",
	maintainer="Thomas Müller",
	maintainer_email="tmueller@nvidia.com",
	download_url=f"https://github.com/nvlabs/tiny-cuda-nn",
	license="BSD 3-Clause \"New\" or \"Revised\" License",
	packages=["tinycudann"],
	install_requires=[],
	include_package_data=True,
	zip_safe=False,
	ext_modules=ext_modules,
	cmdclass={"build_ext": BuildExtension}
)
