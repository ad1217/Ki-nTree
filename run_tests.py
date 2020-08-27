import os
import sys
from shutil import copyfile

import config.settings as settings
from common.tools import cprint, create_library
from config import config_interface
from database import inventree_api, inventree_interface
from kicad import kicad_interface
from search.digikey_api import (disable_digikey_api_logger,
                                test_digikey_api_connect)

# SETTINGS
# Enable InvenTree tests
ENABLE_INVENTREE = True
# Enable KiCad tests
ENABLE_KICAD = True
# Enable test samples deletion
ENABLE_DELETE = True
AUTO_DELETE = True
# Set categories to test
PART_CATEGORIES = [
	'Capacitors',
	'Circuit Protections',
	'Connectors',
	'Crystals and Oscillators',
	'Diodes',
	'Inductors',
	'Integrated Circuits',
	'Mechanicals',
	'Power Management',
	'Resistors',
	'RF',
	'Transistors',
]
# Enable tests on extra methods
ENABLE_TEST_METHODS = True
###

# Enable test mode
settings.enable_test_mode()
# Enable InvenTree
settings.set_inventree_enable_flag(True, save=True)
# Enable KiCad
settings.set_kicad_enable_flag(True, save=True)
# Create user configuration files
settings.create_user_config_files()
# Set path to test symbol library
test_library_path = os.path.join(settings.PROJECT_DIR, 'tests', 'TEST.lib')
# Copy test files
copyfile(os.path.join(settings.PROJECT_DIR, 'tests', 'files', 'token_storage.json'),
		 os.path.join(settings.PROJECT_DIR, 'search', 'token_storage.json'))
# Disable API logging
disable_digikey_api_logger()
if not test_digikey_api_connect():
	cprint('[INFO]\tFailed to get Digi-Key API token, aborting.')
	sys.exit(-1)

# Pretty test printing
def pretty_test_print(message: str):
	message = message.ljust(65)
	cprint(message, end='')

# Check result
def check_result(status: str, new_part: bool) -> bool:
	# Build result
	success = False
	if (status == 'original') or (status == 'fake_alternate'):
		if new_part:
			success = True
	elif status == 'alternate_mpn':
		if not new_part:
			success = True
	else:
		pass

	return success

# Load test samples
samples = config_interface.load_file(os.path.abspath(
	os.path.join('tests', 'test_samples.yaml')))
PART_TEST_SAMPLES = {}
for category in PART_CATEGORIES:
	PART_TEST_SAMPLES.update({category: samples[category]})

# Store results
exit_code = 0
kicad_results = {}
inventree_results = {}

if __name__ == '__main__':
	if settings.ENABLE_TEST:
		if ENABLE_INVENTREE:
			pretty_test_print('\n[MAIN]\tConnecting to Inventree')
			inventree_connect = inventree_interface.connect_to_server()
			if inventree_connect:
				cprint(f'[ PASS ]', flush=True)
			else:
				cprint(f'[ FAIL ]', flush=True)
				sys.exit(-1)

		if ENABLE_KICAD or ENABLE_INVENTREE:
			for category in PART_TEST_SAMPLES.keys():
				cprint(f'\n[MAIN]\tCategory: {category.upper()}')
				for number, status in PART_TEST_SAMPLES[category].items():
					kicad_result = False
					inventree_result = False
					# Fetch supplier data
					part_info = inventree_interface.digikey_search(number)
					# Display part to be tested
					pretty_test_print(f'[INFO]\tChecking "{number}" ({status})')

					if ENABLE_KICAD:
						# Translate supplier data to inventree/kicad data
						part_data = inventree_interface.translate_digikey_to_inventree(part_info, [category, None])

						if part_data:
							part_data['IPN'] = number
							part_data['inventree_url'] = part_data['datasheet']

							if settings.AUTO_GENERATE_LIB:
								create_library(os.path.dirname(test_library_path), 'TEST', settings.symbol_template_lib)

							kicad_result, kicad_new_part = kicad_interface.inventree_to_kicad(part_data=part_data,
																						 	  library_path=test_library_path)
							
							# Log result
							if number not in kicad_results.keys():
								kicad_results.update({number: kicad_result})

					if ENABLE_INVENTREE:
						# Adding part information to InvenTree
						categories = [None, None]
						new_part = False
						part_pk = 0
						part_data = {}

						# Get categories
						if part_info:
							categories = inventree_interface.get_categories(part_info)

						# Create part in InvenTree
						if categories[0] and categories[1]:
							new_part, part_pk, part_data = inventree_interface.inventree_create(part_info=part_info,
																								categories=categories)

						inventree_result = check_result(status, new_part)
						pk_list = [data[0] for data in inventree_results.values()]

						if part_pk != 0 and part_pk not in pk_list:
							delete = True
						else:
							delete = False

						# Log results
						inventree_results.update({number: [part_pk, inventree_result, delete]})

					# Combine KiCad and InvenTree for less verbose
					result = False
					if ENABLE_KICAD and ENABLE_INVENTREE:
						result = kicad_result and inventree_result
					else:
						result = kicad_result or inventree_result

					# Print live results
					if result:
						cprint(f'[ PASS ]', flush=True)
					else:
						cprint(f'[ FAIL ]', flush=True)
						exit_code = -1
						if ENABLE_INVENTREE:
							cprint(f'[DBUG]\tnew_part = {new_part}')
							cprint(f'[DBUG]\tpart_pk = {part_pk}')

			# if True:
			# 	if ENABLE_KICAD:
			# 		cprint(f'\nKiCad Results\n-----', silent=not(settings.ENABLE_TEST))
			# 		cprint(kicad_results, silent=not(settings.ENABLE_TEST))
			# 	if ENABLE_INVENTREE:
			# 		cprint(f'\nInvenTree Results\n-----', silent=not(settings.ENABLE_TEST))
			# 		cprint(inventree_results, silent=not(settings.ENABLE_TEST))

		if ENABLE_DELETE:
			if kicad_results or inventree_results:
				if not AUTO_DELETE:
					input('\nPress "Enter" to delete parts...')
				else:
					cprint('')

				if ENABLE_KICAD:
					error = 0

					pretty_test_print('[MAIN]\tDeleting KiCad test parts')
					# Delete all KiCad test parts
					for number, result in kicad_results.items():
						try:
							kicad_interface.delete_part(part_number=number,
														library_path=test_library_path)
						except:
							error += 1
							cprint(f'[KCAD]\tWarning: "{number}" could not be deleted', flush=True)

					if error > 0:
						cprint('[ FAIL ]', flush=True)
						exit_code = -1
					else:
						cprint(f'[ PASS ]', flush=True)

				if ENABLE_INVENTREE:
					error = 0

					pretty_test_print('[MAIN]\tDeleting InvenTree test parts')
					# Delete all InvenTree test parts
					for number, result in inventree_results.items():
						if result[2]:
							try:
								inventree_api.delete_part(part_id=result[0])
							except:
								error += 1

					if error > 0:
						cprint('[ FAIL ]', flush=True)
						exit_code = -1
					else:
						cprint(f'[ PASS ]', flush=True)

		if ENABLE_TEST_METHODS:
			method_results = True
			pretty_test_print('[MAIN]\tChecking untested methods')

			# Fuzzy category matching
			part_info = {'category': 'Capacitors',
						 'subcategory': 'Super'}
			categories = tuple(inventree_interface.get_categories(part_info))
			if not (categories[0] and categories[1]):
				method_results = False

			# Digi-Key search with missing part number
			search = inventree_interface.digikey_search('')
			if search:
				method_results = False

			# Load KiCad library paths
			config_interface.load_library_path(settings.CONFIG_KICAD, silent=True)

			# Add symbol library to user file
			add_symbol_lib = config_interface.add_library_path(user_config_path=settings.CONFIG_KICAD_CATEGORY_MAP,
											  				   category='category_test',
											  				   symbol_library='symbol_library_test')
			if not add_symbol_lib:
				method_results = False

			# Add footprint library to user file
			add_footprint_lib = config_interface.add_footprint_library(user_config_path=settings.CONFIG_KICAD_CATEGORY_MAP,
												   					   category='category_test',
																	   library_folder='footprint_folder_test')
			if not add_footprint_lib:
				method_results = False

			# Add supplier category
			categories = {
					'Capacitors':
							{ 'Super': 'Super' }
			}
			add_category = config_interface.add_supplier_category(categories, settings.CONFIG_DIGIKEY_CATEGORIES)
			if not add_category:
				method_results = False

			if not method_results:
				cprint('[ FAIL ]', flush=True)
				exit_code = -1
			else:
				cprint(f'[ PASS ]', flush=True)

	sys.exit(exit_code)
