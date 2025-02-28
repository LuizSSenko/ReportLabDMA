import json
import os

def trim_coordinates(coords):
    if isinstance(coords, list):
        if coords and isinstance(coords[0], list):
            return [trim_coordinates(c) for c in coords]
        else:
            return coords[:2]
    return coords

def process_feature(feature):
    if 'geometry' in feature and 'coordinates' in feature['geometry']:
        feature['geometry']['coordinates'] = trim_coordinates(feature['geometry']['coordinates'])
    return feature

def process_geojson(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if 'features' in data:
        data['features'] = [process_feature(feature) for feature in data['features']]

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Processed GeoJSON saved to {output_path}")

if __name__ == "__main__":
    # Use the directory of the script to build the file path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_file = os.path.join(base_dir, "map.geojson")
    output_file = os.path.join(base_dir, "map_2d.geojson")
    process_geojson(input_file, output_file)
