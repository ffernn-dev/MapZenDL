import asyncio
import io
import os
import pathlib

import aiohttp
import humanize
import numpy as np
from PIL import Image
from platformdirs import user_cache_dir
from rich.console import Console
from rich.table import Table
from tqdm.asyncio import tqdm
from matplotlib import pyplot as plt


EARTH_CIRCUMFERENCE = 20037508.34278924
URL_BASE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/"
CACHE_DIR = user_cache_dir("mapzenDL", "ffernn")


def epsg_3857_to_pixel(coord, zoom):
	# Returns pixel of the Slippymap tile that the coordinate specifies.
	output = np.zeros([2])
	output[0] = (EARTH_CIRCUMFERENCE + coord[0]) / (2 * EARTH_CIRCUMFERENCE)
	output[1] = (EARTH_CIRCUMFERENCE - coord[1]) / (2 * EARTH_CIRCUMFERENCE)

	n = np.power(2, zoom)
	output *= n
	output = np.modf(output)[0] * 256
	return output.astype(np.uint8)

def epsg_3857_to_tile(coord, zoom):
	# Returns the Slippymap tile that the given EPSG:3857 coordinate falls into
	output = np.zeros([2])
	output[0] = (EARTH_CIRCUMFERENCE + coord[0]) / (2 * EARTH_CIRCUMFERENCE)
	output[1] = (EARTH_CIRCUMFERENCE - coord[1]) / (2 * EARTH_CIRCUMFERENCE)

	n = np.power(2, zoom)
	output *= n
	output = np.floor(output).astype(np.uint32)
	return output

def normalize_height_data(data):
	flat_data = data.flatten()

	min_window = np.percentile(flat_data, 0.005)
	max_window = np.percentile(flat_data, 99.995)

	std_dev = np.std(flat_data)

	actual_min = np.min(flat_data)
	actual_max = np.max(flat_data)

	# Adjust min and max if within 1 standard deviation of windowed values
	min_val = actual_min if abs(actual_min - min_window) <= std_dev else min_window
	max_val = actual_max if abs(actual_max - max_window) <= std_dev else max_window

	normalized_data = (data - min_val) / (max_val - min_val)
	normalized_data = np.clip(normalized_data, 0, 1)  # Clip any overshoots due to outliers

	return normalized_data


class TileSet:
	def __init__(self, bounding_box, zoom):
		self.left, self.bottom = epsg_3857_to_tile(bounding_box[:2], zoom)
		self.right, self.top = epsg_3857_to_tile(bounding_box[2:], zoom)
		self.left_pixel, self.bottom_pixel = epsg_3857_to_pixel(bounding_box[:2], zoom)
		self.right_pixel, self.top_pixel = epsg_3857_to_pixel(bounding_box[:2], zoom)

		self.zoom = zoom

		self.width = self.right - self.left + 1
		self.height = self.bottom - self.top + 1

		self.right_pixel += (self.width - 1) * 256
		self.bottom_pixel += (self.height - 1) * 256

	def count(self):
		# Returns the total number of tiles in the tileset
		return self.width * self.height

	def tiles(self):
		# Returns a list of all tile coordinates contained in the tileset
		tiles = []
		for y in range(self.top, self.bottom + 1):
			for x in range(self.left, self.right + 1):
				tiles.append([self.zoom, x, y])
		return tiles

	def final_resolution(self):
		return (self.width * 256, self.height * 256)


def tile_coords_to_filepath(coordinates):
	coordinate_route = "/".join(map(str, coordinates))
	filepath = coordinate_route + ".png"
	return filepath


async def collect_tiles(queue, indexed_tiles):
	async with aiohttp.ClientSession() as session:
		tasks = [download_tile(session, tile[1], tile[0], queue) for tile in indexed_tiles]
		await tqdm.gather(*tasks, unit="tiles", desc="download")

	# Signal done
	await queue.put(None)


# Checks the cache for the given tile path. If found, returns that,
# if not, downloads and caches the tile.
async def download_tile(session, coords, tile_index, queue):
	image_filepath = tile_coords_to_filepath(coords)
	url = URL_BASE + image_filepath
	save_path = pathlib.Path(os.path.join(CACHE_DIR, image_filepath))
	save_path.parent.mkdir(parents=True, exist_ok=True)

	if save_path.is_file():
		with open(save_path, "rb") as f:
			await queue.put((tile_index, f.read()))
	else:
		async with session.get(url) as response:
			if response.status == 200:
				image_data = await response.read()
				await queue.put((tile_index, image_data))

				with open(save_path, "wb") as f:
					f.write(image_data)
			else:
				print(
					f"Failed to download tile {image_filepath}, error {response.status}"
				)


async def process_tiles(queue, concat_dimensions):
	num_tiles = concat_dimensions[0] * concat_dimensions[1]
	output_image = np.zeros((concat_dimensions[0] * 256, concat_dimensions[1] * 256))

	t = tqdm(total=num_tiles, unit="tiles", desc="process")
	while True:
		input = await queue.get()
		if input is None:
			# No more images to process
			break

		tile_index, image_data = input

		image = Image.open(io.BytesIO(image_data))
		image_array = np.array(image)

		# ugly code but it's doing (red * 256 + green + blue / 256) - 32768
		heightmap = image_array[:, :, 0] * 256 + image_array[:, :, 1] + image_array[:, :, 2] / 256 - 32768
		heightmap[heightmap < 0] = 0

		x = int(tile_index % concat_dimensions[0] * 256)
		y = int(tile_index // concat_dimensions[0] * 256)
		output_image[x:x+256, y:y+256] = heightmap.T

		t.update()

	return output_image


async def main():
	os.makedirs(CACHE_DIR, exist_ok=True)

	console = Console()
	console.print(
		'Input the desired region of terrain as EPSG:3857 coordinates, in the order [left, bottom, right, top].\nTo get these coordinates from a map, you can use https://tools.geofabrik.de/calc/, and copy from the "Simple Copy" textbox.'
	)
	console.print("[cyan]--> ", end="")
	coordinates_input = console.input()
	bounding_box = [
		float(value) for value in coordinates_input.split(",")
	]  # Becomes [left, bottom, right, top]

	table = Table()
	table.add_column("Zoom level", style="cyan", no_wrap=True)
	table.add_column("Tile count")
	table.add_column("Resolution")
	table.add_column("est. File Size")

	for i in range(7, 16):
		ts = TileSet(bounding_box, i)
		res = ts.final_resolution()
		filesize = (res[0] * res[1] * 48) / 8
		table.add_row(
			str(i),
			f"{res[0]}x{res[1]}px",
			str(ts.count()),
			humanize.naturalsize(filesize),
		)

	console.print(table)
	zoom = int(input("Input the desired zoom level for your tiles (0-15) "))

	tileset = TileSet(bounding_box, zoom)
	tiles = tileset.tiles()
	tiles = list(enumerate(tiles))

	queue = asyncio.Queue()
	producer = asyncio.create_task(collect_tiles(queue, tiles))
	consumer = asyncio.create_task(process_tiles(queue, (tileset.width, tileset.height)))

	_, output_data = await asyncio.gather(producer, consumer)
	# Crop the data to the exact requested area
	print(output_data.shape)
	print(tileset.top_pixel, tileset.left_pixel, ",", tileset.bottom_pixel, tileset.right_pixel)
	output_data = output_data[tileset.top_pixel:tileset.bottom_pixel, tileset.left_pixel:tileset.right_pixel]
	print(output_data.shape)

	output_data = (normalize_height_data(output_data) * 65535).astype(np.uint16)
	output_image = Image.fromarray(output_data.T)
	output_image.save("output.tiff", format="TIFF", depth=16)




if __name__ == "__main__":
	asyncio.run(main())
