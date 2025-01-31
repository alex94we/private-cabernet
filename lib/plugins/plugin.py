"""
MIT License

Copyright (C) 2023 ROCKY4546
https://github.com/rocky4546

This file is part of Cabernet

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software
is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.
"""

import logging
import json
import importlib
import importlib.resources
import lib.common.utils as utils

import lib.common.exceptions as exceptions
from lib.config.config_defn import ConfigDefn
from lib.db.db_plugins import DBPlugins
from lib.db.db_config_defn import DBConfigDefn

PLUGIN_CONFIG_DEFN_FILE = 'config_defn.json'
PLUGIN_INSTANCE_DEFN_FILE = 'instance_defn.json'
PLUGIN_MANIFEST_FILE = 'plugin.json'


def register(func):
    """Decorator for registering a new plugin"""
    Plugin._plugin_func = func
    return func


class Plugin:
    # Temporarily used to register the plugin setup() function
    _plugin_func = None
    logger = None

    def __init__(self, _config_obj, _plugin_defn, _plugins_pkg, _plugin_id, _is_external):
        if Plugin.logger is None:
            Plugin.logger = logging.getLogger(__name__)
        self.enabled = True
        self.plugin_path = '.'.join([_plugins_pkg, _plugin_id])
        self.plugin_id = _plugin_id
        self.config_obj = _config_obj
        self.db_configdefn = DBConfigDefn(_config_obj.data)
        self.load_config_defn()

        # plugin is registered after this call, so grab reg data
        self.init_func = Plugin._plugin_func
        self.plugin_settings = {}
        self.plugin_db = DBPlugins(_config_obj.data)
        self.namespace = ''
        self.instances = []
        self.repo_id = None
        self.load_plugin_manifest(_plugin_defn, _is_external)
        if not self.namespace:
            self.enabled = False
            self.logger.debug('1 Plugin disabled in config.ini for {}'.format(self.namespace))
            return
        self.plugin_obj = None
        self.config_obj.data[self.namespace.lower()]['version'] = self.plugin_settings['version']['current']
        if not self.config_obj.data[self.namespace.lower()].get('enabled'):
            self.enabled = False
            self.logger.debug('2 Plugin disabled in config.ini for {}'.format(self.namespace))
            self.db_configdefn.add_config(self.config_obj.data)
            return
        self.load_instances()
        self.logger.notice('Plugin created for {}'.format(self.namespace))

    def terminate(self):
        """
        Removes all has a object from the object and calls any subclasses to also terminate
        Not calling inherited class at this time
        """
        self.enabled = False
        self.config_obj.write(
            self.namespace.lower(), 'enabled', False)

        if self.plugin_obj:
            self.plugin_obj.terminate()
        self.plugin_path = None
        self.plugin_id = None
        self.config_obj = None
        self.db_configdefn = None
        self.init_func = None
        self.plugin_settings = None
        self.plugin_db = None
        self.namespace = None
        self.instances = None
        self.repo_id = None
        self.plugin_obj = None


    def load_config_defn(self):
        try:
            self.logger.debug(
                'Plugin Config Defn file loaded at {}'.format(self.plugin_path))
            defn_obj = ConfigDefn(self.plugin_path, PLUGIN_CONFIG_DEFN_FILE, self.config_obj.data)
            default_config = defn_obj.get_default_config()
            self.config_obj.merge_config(default_config)
            defn_obj.call_oninit(self.config_obj)
            self.config_obj.defn_json.merge_defn_obj(defn_obj)
            for area, area_data in defn_obj.config_defn.items():
                for section, section_data in area_data['sections'].items():
                    for setting in section_data['settings'].keys():
                        new_value = self.config_obj.fix_value_type(
                            section, setting, self.config_obj.data[section][setting])
                        self.config_obj.data[section][setting] = new_value
            self.db_configdefn.add_config(self.config_obj.data)
            defn_obj.terminate()
        except FileNotFoundError:
            self.logger.warning(
                'PLUGIN CONFIG DEFN FILE NOT FOUND AT {}'.format(self.plugin_path))

    def load_instances(self):
        inst_defn_obj = ConfigDefn(self.plugin_path, PLUGIN_INSTANCE_DEFN_FILE, self.config_obj.data, True)
        # determine in the config data whether the instance of this name exists.
        # It would have a section name = 'name-instance'
        self.instances = self.find_instances()
        if len(self.instances) == 0:
            self.enabled = False
            self.config_obj.data[self.namespace.lower()]['enabled'] = False
            self.logger.info('No instances found, disabling plugin {}'.format(self.namespace))
            return
        for inst in self.instances:
            self.plugin_db.save_instance(self.repo_id, self.namespace, inst, '')
            # create a defn with the instance name as the section name. then process it.
            inst_defn_obj.is_instance_defn = False
            for area, area_data in inst_defn_obj.config_defn.items():
                if len(area_data['sections']) != 1:
                    self.logger.error('INSTANCE MUST HAVE ONE AND ONLY ONE SECTION')
                    raise exceptions.CabernetException('plugin defn must have one and only one instance section')
                section = list(area_data['sections'].keys())[0]
                base_section = section.split('_', 1)[0]
                area_data['sections'][base_section + '_' + inst] = area_data['sections'].pop(section)
                if 'label' in self.config_obj.data[base_section + '_' + inst] \
                        and self.config_obj.data[base_section + '_' + inst]['label'] is not None:
                    area_data['sections'][base_section + '_' + inst]['label'] = \
                        self.config_obj.data[base_section + '_' + inst]['label']
                inst_defn_obj.save_defn_to_db()

                default_config = inst_defn_obj.get_default_config()
                self.config_obj.merge_config(default_config)
                inst_defn_obj.call_oninit(self.config_obj)
                self.config_obj.defn_json.merge_defn_obj(inst_defn_obj)
                for area2, area_data2 in inst_defn_obj.config_defn.items():
                    for section, section_data in area_data2['sections'].items():
                        for setting in section_data['settings'].keys():
                            new_value = self.config_obj.fix_value_type(
                                section, setting, self.config_obj.data[section][setting])
                            self.config_obj.data[section][setting] = new_value
        self.db_configdefn.add_config(self.config_obj.data)

    def find_instances(self):
        instances = []
        inst_sec = self.namespace.lower() + '_'
        for section in self.config_obj.data.keys():
            if section.startswith(inst_sec):
                instances.append(section.split(inst_sec, 1)[1])
        return instances

    def load_plugin_manifest(self, _plugin_defn, _is_external):
        self.load_default_settings(_plugin_defn)
        self.import_manifest(_is_external)

    def load_default_settings(self, _plugin_defn):
        for name, attr in _plugin_defn.items():
            self.plugin_settings[name] = attr['default']

    def import_manifest(self, _is_external):
        try:
            json_settings = self.plugin_db.get_plugins(_installed=None, _repo_id=None, _plugin_id=self.plugin_id)

            local_settings = importlib.resources.read_text(self.plugin_path, PLUGIN_MANIFEST_FILE)
            local_settings = json.loads(local_settings)
            local_settings = local_settings['plugin']

            if not json_settings:
                json_settings = local_settings
                json_settings['repoid'] = None
            else:
                json_settings = json_settings[0]
                self.repo_id = json_settings['repoid']
                if not json_settings['version']['current']:
                    json_settings['version']['current'] = local_settings['version']['current']
            json_settings['external'] = _is_external
            json_settings['version']['installed'] = True
            self.namespace = json_settings['name']
            self.plugin_db.save_plugin(json_settings)
            self.logger.debug(
                'Plugin Manifest file loaded at {}'.format(self.plugin_path))
            self.plugin_settings = utils.merge_dict(self.plugin_settings, json_settings, True)

        except FileNotFoundError:
            self.logger.warning(
                'PLUGIN MANIFEST FILE NOT FOUND AT {}'.format(self.plugin_path))

    @property
    def name(self):
        return self.plugin_settings['name']
