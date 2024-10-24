import numpy as np

EARTH_CIRCUMFERENCE = 20037508.34278924

def epsg_3857_to_tile(coord, zoom):
	# Returns the Slippymap tile that the given EPSG:3857 coordinate falls into
	output = np.zeros([2])
	output[0] = (EARTH_CIRCUMFERENCE + coord[0]) / (2 * EARTH_CIRCUMFERENCE)
	output[1] = (EARTH_CIRCUMFERENCE - coord[1]) / (2 * EARTH_CIRCUMFERENCE)

	n = np.power(2, zoom)
	output *= n
	output = np.floor(output).astype(np.int32)
	return output

class TileSet():
	def __init__(self, bounding_box, zoom):
		self.left, self.bottom = epsg_3857_to_tile(bounding_box[:2], zoom)
		self.right, self.top = epsg_3857_to_tile(bounding_box[2:], zoom)

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
				tiles.append([x, y])
		return tiles

def main():
	coordinates_input = input("Use https://tools.geofabrik.de/calc/ to select the area you wish to download, click the \"CD\" tab, copy from the \"Simple Copy\" box, and paste here")
	bounding_box = [float(value) for value in coordinates_input.split(",")] # Becomes [left, bottom, right, top]

	zoom = int(input("What zoom level for tiles should I download? (0-15)"))

	tileset = TileSet(bounding_box, zoom)
	print(tileset.tiles())


if __name__ == "__main__":
	main()
