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

coordinates_input = input("Use https://tools.geofabrik.de/calc/ to select the area you wish to download, click the \"CD\" tab, copy from the \"Simple Copy\" box, and paste here")
coordinates = coordinates_input.split(",") # Becomes [left, bottom, right, top]

resolution = int(input("What zoom level for tiles should I download? (1-14)"))

print(epsg_3857_to_tile(np.array([16086125,-5432235]), 15))
