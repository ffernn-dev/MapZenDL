import asyncio
import os
import pathlib

import aiohttp
import humanize
import numpy as np
from platformdirs import user_cache_dir
from rich.console import Console
from rich.table import Table
from tqdm.asyncio import tqdm

EARTH_CIRCUMFERENCE = 20037508.34278924
URL_BASE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/"
CACHE_DIR = user_cache_dir("mapzenDL", "ffernn")


def epsg_3857_to_tile(coord, zoom):
	# Returns the Slippymap tile that the given EPSG:3857 coordinate falls into
	output = np.zeros([2])
	output[0] = (EARTH_CIRCUMFERENCE + coord[0]) / (2 * EARTH_CIRCUMFERENCE)
	output[1] = (EARTH_CIRCUMFERENCE - coord[1]) / (2 * EARTH_CIRCUMFERENCE)

	n = np.power(2, zoom)
	output *= n
	output = np.floor(output).astype(np.int32)
	return output


class TileSet:
	def __init__(self, bounding_box, zoom):
		self.left, self.bottom = epsg_3857_to_tile(bounding_box[:2], zoom)
		self.right, self.top = epsg_3857_to_tile(bounding_box[2:], zoom)
		self.zoom = zoom

		self.width = self.right - self.left + 1
		self.height = self.bottom - self.top + 1

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


async def collect_tiles(queue, tiles):
	image_filepaths = [tile_coords_to_filepath(coordinates) for coordinates in tiles]
	async with aiohttp.ClientSession() as session:
		tasks = [download_tile(session, url, queue) for url in image_filepaths]
		await asyncio.gather(*tasks)

	# Signal done
	await queue.put(None)


# Checks the cache for the given tile path. If found, returns that,
# if not, downloads and caches the tile.
async def download_tile(session, image_filepath, queue):
	url = URL_BASE + image_filepath
	save_path = pathlib.Path(os.path.join(CACHE_DIR, image_filepath))
	save_path.parent.mkdir(parents=True, exist_ok=True)

	if save_path.is_file():
		print("found in cache, skipping")
		with open(save_path, "rb") as f:
			await queue.put(f.read())
	else:
		async with session.get(url) as response:
			if response.status == 200:
				image_data = await response.read()
				await queue.put(image_data)
				with open(save_path, "wb") as f:
					f.write(image_data)
			else:
				print(
					f"Failed to download tile {image_filepath}, error {response.status}"
				)


async def process_tiles(queue):
	tiled_image = None
	images = []

	while True:
		# Get image data from the queue
		image_data = await queue.get()
		if image_data is None:
			# No more images to process
			break
		pass
		# Convert the image data to a NumPy array, for example using OpenCV or PIL
		# Here you could use PIL: from PIL import Image; np.array(Image.open(io.BytesIO(image_data)))
		# Dummy conversion for demonstration (replace with actual image processing)
		# image_array = np.frombuffer(image_data, dtype=np.uint8)
		# images.append(image_array)

	# Example: tile the images together (replace with your actual tiling logic)
	# if images:
	#    tiled_image = np.concatenate(images, axis=0)  # Simple concatenation for demonstration

	# return tiled_image


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

	queue = asyncio.Queue()
	producer = asyncio.create_task(collect_tiles(queue, tiles))
	consumer = asyncio.create_task(process_tiles(queue))

	await asyncio.gather(producer, consumer)


if __name__ == "__main__":
	asyncio.run(main())
