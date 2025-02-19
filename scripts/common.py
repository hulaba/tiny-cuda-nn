#!/usr/bin/env python3

# Copyright (c) 2020-2022, NVIDIA CORPORATION.  All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without modification, are permitted
# provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright notice, this list of
#       conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright notice, this list of
#       conditions and the following disclaimer in the documentation and/or other materials
#       provided with the distribution.
#     * Neither the name of the NVIDIA CORPORATION nor the names of its contributors may be used
#       to endorse or promote products derived from this software without specific prior written
#       permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
# FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL NVIDIA CORPORATION BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TOR (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
from pathlib import Path, PurePosixPath
import numpy as np
import pyexr as exr
from scipy.ndimage.filters import convolve1d
import struct

import PIL.Image
PIL.Image.MAX_IMAGE_PIXELS = 10000000000

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT_DIR/"scripts"

def mse2psnr(x):
    return -10.*np.log(x)/np.log(10.)

def sanitize_path(path):
	return str(PurePosixPath(path.relative_to(ROOT_DIR)))

def write_image_pillow(img_file, img, quality):
	img_array = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
	im = PIL.Image.fromarray(img_array)
	if os.path.splitext(img_file)[1] == ".jpg":
		im = im.convert("RGB") # Bake the alpha channel
	im.save(img_file, quality=quality, subsampling=0)

def read_image_pillow(img_file):
	img = PIL.Image.open(img_file, "r")
	if os.path.splitext(img_file)[1] == ".jpg":
		img = img.convert("RGB")
	else:
		img = img.convert("RGBA")
	img = np.asarray(img).astype(np.float32)
	return img / 255.0

def srgb_to_linear(img):
	limit = 0.04045
	return np.where(img > limit, np.power((img + 0.055) / 1.055, 2.4), img / 12.92)

def linear_to_srgb(img):
	limit = 0.0031308
	return np.where(img > limit, 1.055 * (img ** (1.0 / 2.4)) - 0.055, 12.92 * img)

def read_image(file):
	if os.path.splitext(file)[1] == ".exr":
		img = exr.read(file).astype(np.float32)
	elif os.path.splitext(file)[1] == ".bin":
		with open(file, "rb") as f:
			bytes = f.read()
			h, w = struct.unpack("ii", bytes[:8])
			img = np.frombuffer(bytes, dtype=np.float16, count=h*w*4, offset=8).astype(np.float32).reshape([h, w, 4])
	else:
		img = read_image_pillow(file)
		if img.shape[2] == 4:
			img[...,0:3] = srgb_to_linear(img[...,0:3])
			# Premultiply alpha
			img[...,0:3] *= img[...,3:4]
		else:
			img = srgb_to_linear(img)
	return img

def write_image(file, img, quality=95):
	if os.path.splitext(file)[1] == ".exr":
		img = exr.write(file, img)
	elif os.path.splitext(file)[1] == ".bin":
		if img.shape[2] < 4:
			img = np.dstack((img, np.ones([img.shape[0], img.shape[1], 4 - img.shape[2]])))
		with open(file, "wb") as f:
			f.write(struct.pack("ii", img.shape[0], img.shape[1]))
			f.write(img.astype(np.float16).tobytes())
	else:
		if img.shape[2] == 4:
			img = np.copy(img)
			# Unmultiply alpha
			img[...,0:3] = np.divide(img[...,0:3], img[...,3:4], out=np.zeros_like(img[...,0:3]), where=img[...,3:4] != 0)
			img[...,0:3] = linear_to_srgb(img[...,0:3])
		else:
			img = linear_to_srgb(img)
		write_image_pillow(file, img, quality)

def write_image_gamma(file, img, gamma, quality=95):
	if os.path.splitext(file)[1] == ".exr":
		img = exr.write(file, img)
	else:
		img = img**(1.0/gamma) # this will break alpha channels
		write_image_pillow(file, img, quality)

def trim(error, skip=0.000001):
	error = np.sort(error.flatten())
	size = error.size
	skip = int(skip * size)
	return error[skip:size-skip].mean()

def luminance(a):
	a = np.maximum(0, a)**0.4545454545
	return 0.2126 * a[:,:,0] + 0.7152 * a[:,:,1] + 0.0722 * a[:,:,2]

def SSIM(a, b):
	def blur(a):
		k = np.array([0.120078, 0.233881, 0.292082, 0.233881, 0.120078])
		x = convolve1d(a, k, axis=0)
		return convolve1d(x, k, axis=1)
	a = luminance(a)
	b = luminance(b)
	mA = blur(a)
	mB = blur(b)
	sA = blur(a*a) - mA**2
	sB = blur(b*b) - mB**2
	sAB = blur(a*b) - mA*mB
	c1 = 0.01**2
	c2 = 0.03**2
	p1 = (2.0*mA*mB + c1)/(mA*mA + mB*mB + c1)
	p2 = (2.0*sAB + c2)/(sA + sB + c2)
	error = p1 * p2
	return error

def L1(img, ref):
	return np.abs(img - ref)

def APE(img, ref):
	return L1(img, ref) / (1e-2 + ref)

def SAPE(img, ref):
	return L1(img, ref) / (1e-2 + (ref + img) / 2.)

def L2(img, ref):
	return (img - ref)**2

def RSE(img, ref):
	return L2(img, ref) / (1e-2 + ref**2)

def rgb_mean(img):
	return np.mean(img, axis=2)

def compute_error_img(metric, img, ref):
	img[np.logical_not(np.isfinite(img))] = 0
	img = np.maximum(img, 0.)
	if metric == "MAE":
		return L1(img, ref)
	elif metric == "MAPE":
		return APE(img, ref)
	elif metric == "SMAPE":
		return SAPE(img, ref)
	elif metric == "MSE":
		return L2(img, ref)
	elif metric == "MScE":
		return L2(np.clip(img, 0.0, 1.0), np.clip(ref, 0.0, 1.0))
	elif metric == "MRSE":
		return RSE(img, ref)
	elif metric == "MtRSE":
		return trim(RSE(img, ref))
	elif metric == "MRScE":
		return RSE(np.clip(img, 0, 100), np.clip(ref, 0, 100))
	elif metric == "SSIM":
		return SSIM(np.clip(img, 0.0, 1.0), np.clip(ref, 0.0, 1.0))

	raise ValueError(f"Unknown metric: {metric}.")

def compute_error(metric, img, ref):
	metric_map = compute_error_img(metric, img, ref)
	metric_map[np.logical_not(np.isfinite(metric_map))] = 0
	if len(metric_map.shape) == 3:
		metric_map = np.mean(metric_map, axis=2)
	mean = np.mean(metric_map)
	return mean
