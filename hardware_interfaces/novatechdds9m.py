import gtk
from output_classes import AO, DO, DDS
from tab_base_classes import Tab, Worker, define_state
from time import time
class novatechdds9m(Tab):
    # Capabilities
    num_DDS = 4
       
    base_units = {'freq':'Hz',          'amp':'Arb.', 'phase':'Degrees'}
    base_min =   {'freq':0.0,           'amp':0,      'phase':0}
    base_max =   {'freq':170.0*10.0**6, 'amp':1023,   'phase':360}
    base_step =  {'freq':10**6,         'amp':1,      'phase':1}
        
    def __init__(self,BLACS,notebook,settings,restart=False):
        Tab.__init__(self,BLACS,NovatechDDS9mWorker,notebook,settings)
        self.settings = settings
        self.device_name = settings['device_name']
        self.fresh = False # whether to force a full reprogramming of table mode
        self.static_mode = True
        self.destroy_complete = False
        self.com_port = self.settings['connection_table'].find_by_name(self.settings["device_name"]).BLACS_connection

        
        self.queued_static_updates = 0
        
        # PyGTK stuff:
        self.builder = gtk.Builder()
        self.builder.add_from_file('hardware_interfaces/novatechdds9m.glade')
        self.builder.connect_signals(self)
        
        self.toplevel = self.builder.get_object('toplevel')
        self.main_view = self.builder.get_object('main_vbox')
        self.checkbutton_fresh = self.builder.get_object('force_fresh_program')
        self.smart_disabled = self.builder.get_object('hbox_fresh_program')
        self.smart_enabled = self.builder.get_object('hbox_smart_in_use')
        self.builder.get_object('title').set_text(self.settings["device_name"]+" - Port: "+self.com_port)
                
        # Get the widgets needed for showing the prompt to push/pull values to/from the Novatech
        self.changed_widgets = {'changed_vbox':self.builder.get_object('changed_vbox')}                
                
        self.dds_outputs = []
        self.outputs_by_widget = {}
        for i in range(self.num_DDS):        
            # get the widgets for the changed values detection (push/pull to/from device)
            self.changed_widgets['ch_%d_vbox'%i] = self.builder.get_object('changed_vbox_ch_%d'%i)
            self.changed_widgets['ch_%d_label'%i] = self.builder.get_object('new_ch_label_%d'%i)
            self.changed_widgets['ch_%d_push_radio'%i] = self.builder.get_object('radiobutton_push_BLACS_%d'%i)
            self.changed_widgets['ch_%d_pull_radio'%i] = self.builder.get_object('radiobutton_pull_remote_%d'%i)
        
            # Generate a unique channel name (unique to the device instance,
            # it does not need to be unique to BLACS)
            channel = 'Channel %d'%i
            # Get the connection table entry object
            conn_table_entry = self.settings['connection_table'].find_child(self.settings['device_name'],'channel %d'%i)
            # Get the name of the channel
            # If no name exists, it MUST be set to '-'
            name = conn_table_entry.name if conn_table_entry else '-'
            
            # Set the label to reflect the connected channels name:
            self.builder.get_object('channel_%d_label'%i).set_text(channel + ' - ' + name)
            
            # Loop over freq,amp,phase and create AO objects for each
            ao_objects = {}
            sub_chnl_list = ['freq','amp','phase']
            for sub_chnl in sub_chnl_list:
                # get the widgets for the changed values detection (push/pull to/from device)
                for age in ['old','new']:
                    self.changed_widgets['ch_%d_%s_%s'%(i,age,sub_chnl)] = self.builder.get_object('%s_%s_%d'%(age,sub_chnl,i))
                    self.changed_widgets['ch_%d_%s_%s_unit'%(i,age,sub_chnl)] = self.builder.get_object('%s_%s_unit_%d'%(age,sub_chnl,i))
                
                
                calib = None
                calib_params = {}
                
                # find the calibration details for this subchannel
                # TODO: Also get their min/max values
                if conn_table_entry:
                    if (conn_table_entry.name+'_'+sub_chnl) in conn_table_entry.child_list:
                        sub_chnl_entry = conn_table_entry.child_list[conn_table_entry.name+'_'+sub_chnl]
                        if sub_chnl_entry != "None":
                            calib = sub_chnl_entry.unit_conversion_class
                            calib_params = eval(sub_chnl_entry.unit_conversion_params)
                
                # Get the widgets from the glade file
                spinbutton = self.builder.get_object(sub_chnl+'_chnl_%d'%i)
                unit_selection = self.builder.get_object(sub_chnl+'_unit_chnl_%d'%i)
                        
                # Make output object:
                ao_objects[sub_chnl] = AO(name+'_'+sub_chnl, 
                                          channel+'_'+sub_chnl, 
                                          spinbutton, 
                                          unit_selection, 
                                          calib, 
                                          calib_params, 
                                          self.base_units[sub_chnl], 
                                          self.program_static, 
                                          self.base_min[sub_chnl], 
                                          self.base_max[sub_chnl], 
                                          self.base_step[sub_chnl])
                # Set default values:
                ao_objects[sub_chnl].update(settings)            
                
                # Store outputs keyed by widget, so that we can look them up in gtk callbacks:
                self.outputs_by_widget[spinbutton.get_adjustment()] = i, sub_chnl, ao_objects[sub_chnl]
            # Get the widgets for the DDS:
            
            gate_checkbutton = self.builder.get_object("amp_switch_%d"%i)       
            #gate = DO(name+'_gate', channel+'_gate', gate_checkbutton, self.program_static)     
            #self.outputs_by_widget[gate.action] = i, 'gate', gate       
            gate_checkbutton.hide()
            self.dds_outputs.append(DDS(ao_objects['freq'],ao_objects['amp'],ao_objects['phase'],None))     
            
        # Insert our GUI into the viewport provided by BLACS:    
        self.viewport.add(self.toplevel)
        
        # add the status check timeout
        self.statemachine_timeout_add(5000,self.status_monitor)
        
        # Initialise the Novatech DDS9M
        self.initialise_novatech()
        
    @define_state
    def initialise_novatech(self):
        self.queue_work('initialise_novatech', self.com_port, 115200)
        self.do_after('leave_status_monitor')
    
    @define_state
    def status_monitor(self):
        # don't query the device if we are in buffered mode
        if self.static_mode == True:
            self.queue_work('get_current_values')        
            self.do_after('leave_status_monitor')
        else:
            self.main_view.set_sensitive(True)
            self.changed_widgets['changed_vbox'].hide()
            
    def leave_status_monitor(self,_results=None):
        # If a static_update is already queued up, ignore this as it's soon to be obsolete!
        if self.queued_static_updates > 0:
            self.changed_widgets['changed_vbox'].hide()            
            self.main_view.set_sensitive(True)
            return
    
        self.new_values = _results    
        fpv = self.get_front_panel_state()
        # Do the values match the front panel?
        changed = False
        for i in range(self.num_DDS):
            if 'freq%d'%i not in _results or 'freq%d'%i not in _results or 'freq%d'%i not in _results:
                # There is a problem! What do we do here??                
                continue
            if _results['freq%d'%i] != fpv['freq%d'%i] or _results['amp%d'%i] != fpv['amp%d'%i] or _results['phase%d'%i] != fpv['phase%d'%i]:
                # freeze the front panel
                self.main_view.set_sensitive(False)
                
                # show changed vbox
                self.changed_widgets['changed_vbox'].show()
                self.changed_widgets['ch_%d_vbox'%i].show()
                self.changed_widgets['ch_%d_label'%i].set_text(self.builder.get_object("channel_%d_label"%i).get_text())
                changed = True
                
                # populate the labels with the values
                list1 = ['new','old']
                list2 = ['freq','amp','phase']
                
                for name in list1:
                    for subchnl in list2:
                        new_name = name+'_'+subchnl
                        self.changed_widgets['ch_%d_'%i+new_name].set_text(str(_results[subchnl+str(i)] if name == 'new' else fpv[subchnl+str(i)]))
                        self.changed_widgets['ch_%d_'%i+new_name+'_unit'].set_text(self.base_units[subchnl])                       
                                
            else:                
                self.changed_widgets['ch_%d_vbox'%i].hide()
                
        if not changed:
            self.changed_widgets['changed_vbox'].hide()            
            self.main_view.set_sensitive(True)
            
    
        # Update the GUI to reflect the current hardware values:
        # The novatech doesn't have anything to say about the checkboxes;
        # turn them on:
        #for i in range(4):
        #    _results['en%d'%i] = True
        #self.set_front_panel_state(_results)
    
    @define_state
    def continue_after_change(self,widget=None):
        # The basis for the values to be programmed to the novatech are the values just read from the novatech. This provides the greatest level of robustness!
        values = self.new_values
        fpv = self.get_front_panel_state()
        for i, dds in enumerate(self.dds_outputs):
            # do we want to use the front panel values (only applies to channels we showed changed values for)?
            if not self.changed_widgets['ch_%d_pull_radio'%i].get_active() and self.changed_widgets['ch_%d_vbox'%i].get_visible():
                values['freq%d'%i] = fpv['freq%d'%i]
                values['amp%d'%i] = fpv['amp%d'%i]
                values['phase%d'%i] = fpv['phase%d'%i]
                
                # actually make it program.
                # we explicitly do this because setting the widget to the value it is already set to, will never trigger a program call, 
                # since we deliberately ignore such calls to limit possible recursion due to programming errors
                self.program_channel(i, 'freq', fpv['freq%d'%i])
                self.program_channel(i, 'amp', fpv['amp%d'%i])
                self.program_channel(i, 'phase', fpv['phase%d'%i])
                            
        self.main_view.set_sensitive(True)
        self.changed_widgets['changed_vbox'].hide()     
        self.set_front_panel_state(values,program=True)
    
    #@define_state
    def program_channel(self,channel,type,value):
        self.program_static_channel(channel,type,value)
    
    @define_state
    def destroy(self):
        self.queue_work('close_connection')
        self.do_after('leave_destroy')
    
    def leave_destroy(self,_results):
        self.destroy_complete = True
        self.close_tab()
    
    def get_front_panel_state(self):
        return {"freq0":self.dds_outputs[0].freq.value, "amp0":self.dds_outputs[0].amp.value, "phase0":self.dds_outputs[0].phase.value, 
                "freq1":self.dds_outputs[1].freq.value, "amp1":self.dds_outputs[1].amp.value, "phase1":self.dds_outputs[1].phase.value, 
                "freq2":self.dds_outputs[2].freq.value, "amp2":self.dds_outputs[2].amp.value, "phase2":self.dds_outputs[2].phase.value, 
                "freq3":self.dds_outputs[3].freq.value, "amp3":self.dds_outputs[3].amp.value, "phase3":self.dds_outputs[3].phase.value, }
    
    def set_front_panel_state(self, values, program=False):
        """Updates the gui without reprogramming the hardware"""
        for i, dds in enumerate(self.dds_outputs):
            if 'freq%d'%i in values:
                dds.freq.set_value(values['freq%d'%i],program)
            if 'amp%d'%i in values:
                dds.amp.set_value(values['amp%d'%i],program)
            if 'phase%d'%i in values:    
                dds.phase.set_value(values['phase%d'%i],program)
            #if 'en%d'%i in values:
            #    dds.gate.set_state(values['en%d'%i],program=False)
        
    #@define_state
    def program_static(self,widget):
        # Skip if in buffered mode:
        if self.static_mode:
            # The novatech only programs one output at a time. There
            # is no current code which programs many outputs in quick
            # succession, so there is no speed penalty for this:
            channel, type, output = self.outputs_by_widget[widget]
            # If its the user clicking a checkbutton, then really what
            # we're doing is an amplitude change:
            #if type == 'gate':
            #    value = output.state*self.dds_outputs[channel].amp.value
            #    type = 'amp'
            #else:
            value = output.value
                
            self.queued_static_updates += 1
            self.program_static_channel(channel,type,value)
            
    @define_state
    def program_static_channel(self,channel,type,value):
        self.queue_work('program_static',channel, type, value)
        self.do_after('leave_program_static',channel,type)
            
    def leave_program_static(self,channel,type,_results):
        # update the front panel value to what it actually is in the device
        if self.queued_static_updates < 2:
            self.queued_static_updates -= 1
            if self.queued_static_updates < 0:
                self.queued_static_updates = 0
            self.set_front_panel_state({type+str(channel):_results})
    
    @define_state
    def transition_to_buffered(self,h5file,notify_queue):
        self.static_mode = False 
        self.queue_work('program_buffered',self.settings['device_name'],h5file,self.get_front_panel_state(),self.fresh)
        self.do_after('leave_program_buffered',notify_queue)        
    
    def leave_program_buffered(self,notify_queue,_results):
        # Enable smart programming:
        self.checkbutton_fresh.show() 
        self.checkbutton_fresh.set_active(False) 
        self.checkbutton_fresh.toggled()
        # These are the final values that the novatech will be in
        # at the end of the run. Store them so that we can use them
        # in transition_to_static:
        self.final_values = _results
        # Notify the queue manager thread that we've finished
        # transitioning to buffered:
        notify_queue.put(self.device_name)
    
    def abort_buffered(self):
        self.transition_to_static(notify_queue=None)
    
    @define_state    
    def transition_to_static(self,notify_queue):
        if notify_queue is None:
            abort = True
        else: abort = False
        self.queue_work('transition_to_static',abort=abort)
        # Tell the queue manager once we're done:
        self.do_after('leave_transition_to_static',notify_queue)
        # Update the gui to reflect the current hardware values:
        if not abort:
            # The final results don't say anything about the checkboxes;
            # turn them on:
            #for i in range(4):
                #self.final_values['en%d'%i] = True
            self.set_front_panel_state(self.final_values)
        self.static_mode=True
    
    def leave_transition_to_static(self,notify_queue,_results):    
        # Tell the queue manager that we're done:
        if notify_queue is not None:
            notify_queue.put(self.device_name)
            
        self.set_front_panel_state(_results)
            
    @define_state
    def toggle_fresh(self,button):
        if button.get_active():
            self.smart_enabled.hide()
            self.smart_disabled.show()
            self.fresh = True
        else:
            self.smart_enabled.show()
            self.smart_disabled.hide()
            self.fresh = False
        
    def get_child(self,type,channel):
        """Allows virtual devices to obtain this tab's output objects"""
        if type == "DDS":
            if channel in range(self.num_DDS):
                return self.dds_outputs[channel]
        return None
        
        
class NovatechDDS9mWorker(Worker):
    def init(self):
        global serial; import serial
        global h5py; import h5py
        self.smart_cache = {'STATIC_DATA': None, 'TABLE_DATA': ''}
        
    def initialise_novatech(self,port,baud_rate):
        self.connection = serial.Serial(port, baudrate = baud_rate, timeout=0.1)
        self.connection.readlines()
        
        self.connection.write('e d\r\n')
        response = self.connection.readline()
        if response == 'e d\r\n':
            # if echo was enabled, then the command to disable it echos back at us!
            response = self.connection.readline()
        if response != "OK\r\n":
            raise Exception('Error: Failed to execute command: "e d". Cannot connect to the device.')
        
        self.connection.write('I a\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I a"')
        
        self.connection.write('m 0\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "m 0"')
        
        return self.get_current_values()
        
    def get_current_values(self):
        # Get the currently output values:
        self.connection.write('QUE\r\n')
        try:
            response = [self.connection.readline() for i in range(5)]
        except socket.timeout:
            raise Exception('Failed to execute command "QUE". Cannot connect to device.')
        results = {}
        for i, line in enumerate(response[:4]):
            freq, phase, amp, ignore, ignore, ignore, ignore = line.split()
            # Convert hex multiple of 0.1 Hz to MHz:
            results['freq%d'%i] = float(int(freq,16))/10
            # Convert hex to int:
            results['amp%d'%i] = int(amp,16)
            # Convert hex fraction of 16384 to degrees:
            results['phase%d'%i] = int(phase,16)*360/16384.0
        return results
        
    def program_static(self,channel,type,value):
        if type == 'freq':
            command = 'F%d %.7f\r\n'%(channel,value/10.0**6)
            self.connection.write(command)
            if self.connection.readline() != "OK\r\n":
                raise Exception('Error: Failed to execute command: %s'%command)
        elif type == 'amp':
            command = 'V%d %u\r\n'%(channel,value)
            self.connection.write(command)
            if self.connection.readline() != "OK\r\n":
                raise Exception('Error: Failed to execute command: %s'%command)
        elif type == 'phase':
            command = 'P%d %u\r\n'%(channel,value*16384/360)
            self.connection.write(command)
            if self.connection.readline() != "OK\r\n":
                raise Exception('Error: Failed to execute command: %s'%command)
        else:
            raise TypeError(type)
        # Now that a static update has been done, we'd better invalidate the saved STATIC_DATA:
        self.smart_cache['STATIC_DATA'] = None
        
        return self.get_current_values()[type+str(channel)]
       
    def program_buffered(self,device_name,h5file,initial_values,fresh):
        # Store the initial values in case we have to abort and restore them:
        self.initial_values = initial_values
        # Store the final values to for use during transition_to_static:
        self.final_values = {}
        with h5py.File(h5file) as hdf5_file:
            group = hdf5_file['/devices/'+device_name]
            # If there are values to set the unbuffered outputs to, set them now:
            if 'STATIC_DATA' in group:
                data = group['STATIC_DATA'][0]
                if fresh or data != self.smart_cache['STATIC_DATA']:
                    self.logger.debug('Static data has changed, reprogramming.')
                    self.smart_cache['SMART_DATA'] = data
                    self.connection.write('F2 %f\r\n'%(data['freq2']/10.0**7))
                    self.connection.readline()
                    self.connection.write('V2 %u\r\n'%(data['amp2']))
                    self.connection.readline()
                    self.connection.write('P2 %u\r\n'%(data['phase2']))
                    self.connection.readline()
                    self.connection.write('F3 %f\r\n'%(data['freq3']/10.0**7))
                    self.connection.readline()
                    self.connection.write('V3 %u\r\n'%data['amp3'])
                    self.connection.readline()
                    self.connection.write('P3 %u\r\n'%data['phase3'])
                    self.connection.readline()
                    
                    # Save these values into final_values so the GUI can
                    # be updated at the end of the run to reflect them:
                    self.final_values['freq2'] = data['freq2']/10.0
                    self.final_values['freq3'] = data['freq3']/10.0
                    self.final_values['amp2'] = data['amp2']
                    self.final_values['amp3'] = data['amp3']
                    self.final_values['phase2'] = data['phase2']*360/16384.0
                    self.final_values['phase3'] = data['phase3']*360/16384.0
                    
            # Now program the buffered outputs:
            if 'TABLE_DATA' in group:
                data = group['TABLE_DATA'][:]
                for i, line in enumerate(data):
                    st = time()
                    oldtable = self.smart_cache['TABLE_DATA']
                    for ddsno in range(2):
                        if fresh or i >= len(oldtable) or (line['freq%d'%ddsno],line['phase%d'%ddsno],line['amp%d'%ddsno]) != (oldtable[i]['freq%d'%ddsno],oldtable[i]['phase%d'%ddsno],oldtable[i]['amp%d'%ddsno]):
                            self.connection.write('t%d %04x %08x,%04x,%04x,ff\r\n '%(ddsno, i,line['freq%d'%ddsno],line['phase%d'%ddsno],line['amp%d'%ddsno]))
                            self.connection.readline()
                    et = time()
                    tt=et-st
                    self.logger.debug('Time spent on line %s: %s'%(i,tt))
                # Store the table for future smart programming comparisons:
                try:
                    self.smart_cache['TABLE_DATA'][:len(data)] = data
                    self.logger.debug('Stored new table as subset of old table')
                except: # new table is longer than old table
                    self.smart_cache['TABLE_DATA'] = data
                    self.logger.debug('New table is longer than old table and has replaced it.')
                    
                # Get the final values of table mode so that the GUI can
                # reflect them after the run:
                self.final_values['freq0'] = data[-1]['freq0']/10.0
                self.final_values['freq1'] = data[-1]['freq1']/10.0
                self.final_values['amp0'] = data[-1]['amp0']
                self.final_values['amp1'] = data[-1]['amp1']
                self.final_values['phase0'] = data[-1]['phase0']*360/16384.0
                self.final_values['phase1'] = data[-1]['phase1']*360/16384.0
                
            # Transition to table mode:
            self.connection.write('m t\r\n')
            self.connection.readline()
            # Transition to hardware updates:
            self.connection.write('I e\r\n')
            self.connection.readline()
            # We are now waiting for a rising edge to trigger the output
            # of the second table pair (first of the experiment)
            return self.final_values
            
    def transition_to_static(self,abort = False):
        self.connection.write('m 0\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "m 0"')
        self.connection.write('I a\r\n')
        if self.connection.readline() != "OK\r\n":
            raise Exception('Error: Failed to execute command: "I a"')
        if abort:
            # If we're aborting the run, then we need to reset DDSs 2 and 3 to their initial values.
            # 0 and 1 will already be in their initial values. We also need to invalidate the smart
            # programming cache for them.
            values = self.initial_values
            DDSs = [2,3]
            self.smart_cache['STATIC_DATA'] = None
        else:
            # If we're not aborting the run, then we need to set DDSs 0 and 1 to their final values.
            # 2 and 3 will already be in their final values.
            values = self.final_values
            DDSs = [0,1]
            
        # only program the channels that we need to
        for ddsnumber in DDSs:
            for subchnl in ['freq','amp','phase']:            
                self.program_static(ddsnumber,subchnl,values[subchnl+'%d'%ddsnumber])
            
        # return the current values in the novatech
        return self.get_current_values()
                     
    def close_connection(self):
        self.connection.close()
        