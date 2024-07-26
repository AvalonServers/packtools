import argparse
import os
import json
from nbt import nbt

def validate_nbt(path: str) -> bool:
  with open(path, 'rb') as f:
    if len(f.read()) == 0:
      return False
  return True

def get_world_dat(world: str) -> str:
  dat = os.path.join(world, 'level.dat')
  if os.path.exists(dat) and validate_nbt(dat):
    return dat
  
  dat = os.path.join(world, 'level.dat_old')
  if os.path.exists(dat) and validate_nbt(dat):
    return dat

  raise Exception('unable to find level.dat, invalid world?')

def transform_registry(key, data, mapping) -> int:
  count = 0
  for entry in data['ids']:
    new_name = mapping.get('registries', {}).get(key, {}).get(entry['K'].value, None)
    if new_name != None:
      print(entry['K'].value)
      entry['K'].value = new_name
      count += 1

    # item_key = entry['K'].value.split(':')
    # if len(item_key) != 2:
    #   raise Exception('expected 2 components of id key')

    # namespace = item_key[0]
    # name = item_key[1]

    

    # new_namespace = mapping.get('namespaces', {}).get(namespace, None)
    # if new_namespace != None:
    #   namespace = new_namespace

    # new_namespace = mapping.

    # entry['K'].value = ':'.join([namespace, name])

    
  
  return count

def transform(world_path: str, mapping_path: str) -> int:
  count = 0
  with open(mapping_path, 'r') as f:
    mapping = json.load(f)

  world_dat = get_world_dat(world_path)
  nbtfile = nbt.NBTFile(world_dat, 'rb')

  for key, data in nbtfile['FML']['Registries'].items():
    count += transform_registry(key, data, mapping)

  nbtfile.write_file()
  return count

parser = argparse.ArgumentParser(prog='remap', description='Remap Minecraft registry IDs')
parser.add_argument('-w', '--world', required=True, help='Path to the world')
parser.add_argument('-m', '--mapping', default='ids.yaml', required=True, help='Path to the mapping file')
args = parser.parse_args()

count = transform(args.world, args.mapping)
print(f'remapped {count} references')
