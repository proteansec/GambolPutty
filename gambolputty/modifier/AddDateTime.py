# -*- coding: utf-8 -*-
import Utils
import BaseThreadedModule
import Decorators


@Decorators.ModuleDocstringParser
class AddDateTime(BaseThreadedModule.BaseThreadedModule):
    """
    Add a field with the current datetime.

    Configuration template:

    - AddDateTime:
        target_field:        # <default: '@timestamp'; type: string; is: optional>
        format:              # <default: '%Y-%m-%dT%H:%M:%S'; type: string; is: optional>
        receivers:
          - NextModule
    """

    module_type = "modifier"
    """Set module type"""

    def configure(self, configuration):
        # Call parent configure method
        BaseThreadedModule.BaseThreadedModule.configure(self, configuration)
        self.format = self.getConfigurationValue('format')
        self.target_field = self.getConfigurationValue('target_field')

    def handleEvent(self, event):
        event[self.target_field] = Utils.mapDynamicValue(self.format, event, use_strftime=True)
        yield event