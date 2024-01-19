"""
Be able to load a trained policy
Generate rollout data
Works for both Villarreal and Ours
Specific to Intersection scenario

Notes: 
1. Values 1000 occur on space headway
2. For RL types, there is training involved, so the inflow vehicles are IDM at training and during test have to be ModifiedIDM
"""

import argparse
import gym
import numpy as np
import os
import sys
import time

import ray
try:
    from ray.rllib.agents.agent import get_agent_class
except ImportError:
    from ray.rllib.agents.registry import get_agent_class
from ray.tune.registry import register_env

from flow.core.util import emission_to_csv
from flow.utils.registry import make_create_env
from flow.utils.rllib import get_flow_params
from flow.utils.rllib import get_rllib_config
from flow.utils.rllib import get_rllib_pkl

import json 
from common_args import update_arguments
from flow.density_aware_util import get_shock_model, get_time_steps

EXAMPLE_USAGE = """
example usage:
    python ./visualizer_rllib.py /ray_results/experiment_dir/result_dir 1

Here the arguments are:
1 - the path to the simulation results
2 - the number of the checkpoint
"""
def get_fresh_shock_ids(env, ):

    # only certain vehicle flows contain shockable (human) vehicles≠
    shockable_flow = ['flow_20.', 'flow_00.']
    sample_vehicles = 4 # How many vehicles to shock at a time
    current_shockable_vehicles  = []

    # human vehicles to shock have to be identified by which edge they are on and their position.
    all_ids = env.k.vehicle.get_ids()
    north_south_hv_ids = [veh_id for veh_id in all_ids if any(x in veh_id for x in shockable_flow)]
    
    for vid in north_south_hv_ids:
        edge = env.k.vehicle.get_edge(vid)
        pos = env.k.vehicle.get_position(vid)

        # If a vehicle is in an outgoing edge `right1_0` or `left0_0` only allowed to shock if position is less than 65
        if edge == "left0_0" or edge == "right1_0":
            if pos < 165:
                current_shockable_vehicles.append(vid)

        # Else if the vehicle is in an incoming egde `left1_0` or `right0_0` only allowed to shock if position is greater than 135
        elif edge == "left1_0" or edge == "right0_0":
            if pos > 135:
                current_shockable_vehicles.append(vid)
        else: 
            # If a vehicle is in the center, just add it
            current_shockable_vehicles.append(vid)
    
    # Now randomly select sample_vehicles number of  vehicles
    shock_ids = np.random.choice(current_shockable_vehicles, sample_vehicles, replace=False)
    print("Shocking vehicles", shock_ids)

    return shock_ids

def visualizer_rllib(args):
    """Visualizer for RLlib experiments.

    This function takes args (see function create_parser below for
    more detailed information on what information can be fed to this
    visualizer), and renders the experiment associated with it.
    """
    result_dir = args.result_dir if args.result_dir[-1] != '/' \
        else args.result_dir[:-1]

    config = get_rllib_config(result_dir)

    # check if we have a multiagent environment but in a
    # backwards compatible way
    if config.get('multiagent', {}).get('policies', None):
        multiagent = True
        pkl = get_rllib_pkl(result_dir)
        config['multiagent'] = pkl['multiagent']
    else:
        multiagent = False

    # Run on only one cpu for rendering purposes
    config['num_workers'] = 0

    # Grab the config and make modifications
    flow_params_modify = json.loads(config["env_config"]["flow_params"])

    # Veh [0] are humans. Change acceleration controller type
    flow_params_modify["veh"][0]["acceleration_controller"] = ["ModifiedIDMController", {"noise": args.noise, # Just need to specify as string
                                                                                            "shock_vehicle": True}] 
    
    flow_params_modify["sim"]["sim_step"] = args.sim_step

    flow_params_modify["env"]["horizon"] = args.horizon
    flow_params_modify["env"]["warmup_steps"] = args.warmup

    # when VENTER is changed, many things will have to change.
    # change all depart speeds
    # Change all depart speeds
    for inflow in flow_params_modify["net"]["inflows"]["_InFlows__flows"]:
        inflow["departSpeed"] = args.venter

    for vehicle in flow_params_modify["veh"]:
        vehicle['car_following_params']['controller_params']['maxSpeed'] = args.venter

    flow_params_modify["env"]["additional_params"]["target_velocity"] = args.venter + 5 # venter + 5
    # similarly in net there is a limit to velocity
    flow_params_modify["net"]["additional_params"]["speed_limit"] = args.venter + 5

    flow_params_modify["net"]["long_length"] = args.long_length
    flow_params_modify["net"]["short_length"] = args.short_length
    # Set the inflow value 
    # This is essentially the same scheme as the RL + classic config files
    # Total inflow should be equal to the args_inflow 
    # The only way to change inflow is to change the vehicle per hour values
    # There are a total of 6 inflows, 4 directions for humans + 2 directions for rl

    args_inflow = args.inflow
    av_frac = args.av_frac

    inflows = flow_params_modify['net']['inflows']['_InFlows__flows']
    # 0 is left HV, 1 is left RV, 2 is right HV, 3 is right RV, 4 and 5 are east and west HV
    #print("Inflows", inflows)

    # inflows is a list copy it 
    new_inflows = inflows.copy()

    # first split the inflow into 2, 25 % on the two sides
    east_west_inflow = int(0.25*args_inflow)
    
    # Now split the remaining inflow
    rv_per_side = int(av_frac*int(0.75*args_inflow))
    hv_per_side = int((1-av_frac)*int(0.75*args_inflow))
    
    new_inflows[0]['vehsPerHour'] = hv_per_side
    new_inflows[1]['vehsPerHour'] = rv_per_side
    new_inflows[2]['vehsPerHour'] = hv_per_side
    new_inflows[3]['vehsPerHour'] = rv_per_side
    new_inflows[4]['vehsPerHour'] = east_west_inflow
    new_inflows[5]['vehsPerHour'] = east_west_inflow

    #print("New inflows", new_inflows)
    flow_params_modify['net']['inflows']['_InFlows__flows'] = new_inflows

    # Dump the modifications to config
    config["env_config"]["flow_params"] = json.dumps(flow_params_modify)

    flow_params = get_flow_params(config)

    # Hack for old pkl files
    # TODO(ev) remove eventually
    sim_params = flow_params['sim']
    setattr(sim_params, 'num_clients', 1)

    # for hacks for old pkl files TODO: remove eventually
    if not hasattr(sim_params, 'use_ballistic'):
        sim_params.use_ballistic = False

    # Determine agent and checkpoint
    config_run = config['env_config']['run'] if 'run' in config['env_config'] \
        else None
    if args.run and config_run:
        if args.run != config_run:
            print('visualizer_rllib.py: error: run argument '
                  + '\'{}\' passed in '.format(args.run)
                  + 'differs from the one stored in params.json '
                  + '\'{}\''.format(config_run))
            sys.exit(1)
    if args.run:
        agent_cls = get_agent_class(args.run)
    elif config_run:
        agent_cls = get_agent_class(config_run)
    else:
        print('visualizer_rllib.py: error: could not find flow parameter '
              '\'run\' in params.json, '
              'add argument --run to provide the algorithm or model used '
              'to train the results\n e.g. '
              'python ./visualizer_rllib.py /tmp/ray/result_dir 1 --run PPO')
        sys.exit(1)

    sim_params.restart_instance = True

    dir_path = os.path.dirname(os.path.realpath(__file__))
    rl_folder_name = f"{args.method}_stability" if args.stability else args.method
    emission_path = f"{dir_path}/test_time_rollout/{rl_folder_name}" #'{0}/test_time_rollout/'.format(dir_path)

    sim_params.emission_path = emission_path if args.gen_emission else None

    # Create and register a gym+rllib env
    create_env, env_name = make_create_env(params=flow_params, version=0)
    register_env(env_name, create_env)

    # check if the environment is a single or multiagent environment, and
    # get the right address accordingly
    # single_agent_envs = [env for env in dir(flow.envs)
    #                      if not env.startswith('__')]

    # if flow_params['env_name'] in single_agent_envs:
    #     env_loc = 'flow.envs'
    # else:
    #     env_loc = 'flow.envs.multiagent'

    # Start the environment with the gui turned on and a path for the
    # emission file
    env_params = flow_params['env']
    env_params.restart_instance = False
    if args.evaluate:
        env_params.evaluate = True

    # lower the horizon if testing
    if args.horizon:
        config['horizon'] = args.horizon
        env_params.horizon = args.horizon

    # create the agent that will be used to compute the actions
    agent = agent_cls(env=env_name, config=config)
    checkpoint = result_dir + '/checkpoint_' + args.checkpoint_num
    checkpoint = checkpoint + '/checkpoint-' + args.checkpoint_num
    agent.restore(checkpoint)

    if hasattr(agent, "local_evaluator") and \
            os.environ.get("TEST_FLAG") != 'True':
        env = agent.local_evaluator.env
    else:
        env = gym.make(env_name)

    # if args.render_mode == 'sumo_gui':
    #     env.sim_params.render = True  # set to True after initializing agent and env

    if args.render: 
        env.sim_params.render = True
    else: 
        env.sim_params.render = False

    if multiagent:
        rets = {}
        # map the agent id to its policy
        policy_map_fn = config['multiagent']['policy_mapping_fn']
        for key in config['multiagent']['policies'].keys():
            rets[key] = []
    else:
        rets = []

    if config['model']['use_lstm']:
        use_lstm = True
        if multiagent:
            state_init = {}
            # map the agent id to its policy
            policy_map_fn = config['multiagent']['policy_mapping_fn']
            size = config['model']['lstm_cell_size']
            for key in config['multiagent']['policies'].keys():
                state_init[key] = [np.zeros(size, np.float32),
                                   np.zeros(size, np.float32)]
        else:
            state_init = [
                np.zeros(config['model']['lstm_cell_size'], np.float32),
                np.zeros(config['model']['lstm_cell_size'], np.float32)
            ]
    else:
        use_lstm = False

    # if restart_instance, don't restart here because env.reset will restart later
    if not sim_params.restart_instance:
        env.restart_simulation(sim_params=sim_params, render=sim_params.render)

    # Simulate and collect metrics
    final_outflows = []
    final_inflows = []
    mean_speed = []
    std_speed = []

    # no need warmup offset, its already set to 4400
    shock_start_time = args.shock_start_time #- args.warmup
    shock_end_time = args.shock_end_time #- args.warmup

    for i in range(args.num_rollouts):
        vel = []
        state = env.reset()
        if multiagent:
            ret = {key: [0] for key in rets.keys()}
        else:
            ret = 0

        # shock related. Reset to zero for each rollout.
        shock_counter = 0
        current_duration_counter = 0

        shock_model_id = -1 if args.stability else args.shock_model
        if args.stability:
            # A standard velocity perturbation of 2 m/s is applied for 10 timesteps  
            # intensities, durations, frequency = get_shock_model(-1, length=220) 
            intensities, durations, frequency = (np.asarray([3]), np.asarray([1]), 1) # 1 second means 10 timesteps 
        else:
            intensities, durations, frequency =  get_shock_model(shock_model_id, network_scaler=3, bidirectional=False, high_speed=False)
        # Uniquely sampled for each rollout 
        shock_times = get_time_steps(durations, frequency, shock_start_time, shock_end_time)

        for step in range(env_params.horizon):
            vehicles = env.unwrapped.k.vehicle
            speeds = vehicles.get_speed(vehicles.get_ids())
            
            # shock related
            # if stability or else regular shock
            if args.shock and step >= shock_start_time and step <= shock_end_time:

                if step == shock_times[0][0]: # This occurs only once
                    shock_ids = get_fresh_shock_ids(env)

                if args.stability:
                    shock_counter, current_duration_counter, shock_ids  = perform_shock_stability(env,
                                                                                                shock_times,
                                                                                                step,
                                                                                                shock_counter, 
                                                                                                current_duration_counter,
                                                                                                intensities, durations,
                                                                                                frequency)
                else:
                    shock_counter, current_duration_counter, shock_ids = perform_shock(env, 
                                                                                    shock_times, 
                                                                                    step, 
                                                                                    shock_counter, 
                                                                                    current_duration_counter, 
                                                                                    intensities, durations, 
                                                                                    frequency, 
                                                                                        shock_ids)
                              
            # only include non-empty speeds
            if speeds:
                vel.append(np.mean(speeds))

            if multiagent:
                action = {}
                for agent_id in state.keys():
                    if use_lstm:
                        action[agent_id], state_init[agent_id], logits = \
                            agent.compute_action(
                            state[agent_id], state=state_init[agent_id],
                            policy_id=policy_map_fn(agent_id))
                    else:
                        action[agent_id] = agent.compute_action(
                            state[agent_id], policy_id=policy_map_fn(agent_id))
            else:
                action = agent.compute_action(state)
            state, reward, done, _ = env.step(action)
            if multiagent:
                for actor, rew in reward.items():
                    ret[policy_map_fn(actor)][0] += rew
            else:
                ret += reward
            if multiagent and done['__all__']:
                break
            if not multiagent and done:
                break

        if multiagent:
            for key in rets.keys():
                rets[key].append(ret[key])
        else:
            rets.append(ret)
        outflow = vehicles.get_outflow_rate(500)
        final_outflows.append(outflow)
        inflow = vehicles.get_inflow_rate(500)
        final_inflows.append(inflow)
        if np.all(np.array(final_inflows) > 1e-5):
            throughput_efficiency = [x / y for x, y in
                                     zip(final_outflows, final_inflows)]
        else:
            throughput_efficiency = [0] * len(final_inflows)
        mean_speed.append(np.mean(vel))
        std_speed.append(np.std(vel))
        if multiagent:
            for agent_id, rew in rets.items():
                print('Round {}, Return: {} for agent {}'.format(
                    i, ret, agent_id))
        else:
            print('Round {}, Return: {}'.format(i, ret))

    print('==== Summary of results ====')
    print("Return:")
    print(mean_speed)
    if multiagent:
        for agent_id, rew in rets.items():
            print('For agent', agent_id)
            print(rew)
            print('Average, std return: {}, {} for agent {}'.format(
                np.mean(rew), np.std(rew), agent_id))
    else:
        print(rets)
        print('Average, std: {}, {}'.format(
            np.mean(rets), np.std(rets)))

    print("\nSpeed, mean (m/s):")
    print(mean_speed)
    print('Average, std: {}, {}'.format(np.mean(mean_speed), np.std(
        mean_speed)))
    print("\nSpeed, std (m/s):")
    print(std_speed)
    print('Average, std: {}, {}'.format(np.mean(std_speed), np.std(
        std_speed)))

    # Compute arrival rate of vehicles in the last 500 sec of the run
    print("\nOutflows (veh/hr):")
    print(final_outflows)
    print('Average, std: {}, {}'.format(np.mean(final_outflows),
                                        np.std(final_outflows)))
    # Compute departure rate of vehicles in the last 500 sec of the run
    print("Inflows (veh/hr):")
    print(final_inflows)
    print('Average, std: {}, {}'.format(np.mean(final_inflows),
                                        np.std(final_inflows)))
    # Compute throughput efficiency in the last 500 sec of the
    print("Throughput efficiency (veh/hr):")
    print(throughput_efficiency)
    print('Average, std: {}, {}'.format(np.mean(throughput_efficiency),
                                        np.std(throughput_efficiency)))

    # terminate the environment
    env.unwrapped.terminate()

def perform_shock_stability(env,
                            shock_times,
                            step,
                            shock_counter, 
                            current_duration_counter,
                            intensities, durations,
                            frequency):
    """
    Just check the steps and shock the first one after initial population
    flow_10.1 is the controller RL
    flow_00.4 is the shocker vehicle
    flow_00.5 is the follower HV

    # Intensity if the velocity intensity
    """
    
    shock_ids = ['flow_00.4']
    controllers = [env.unwrapped.k.vehicle.get_acc_controller(i) for i in shock_ids]
    for controller in controllers:
        controller.set_shock_time(False)

    # len(durations) is the number of shocks.
    if shock_counter < len(durations) and current_duration_counter >= durations[shock_counter]:
        # reset the setup
        shock_counter += 1
        current_duration_counter = 0
        env.unwrapped.k.vehicle.set_max_speed(shock_ids[0], 8.0) # V enter is 8
        #No need to get fresh shock IDS

    # Only apply shocks for a set number of times
    if shock_counter < frequency: # '<' because shock counter starts from zero
        if step >= shock_times[0][0] and step <= shock_times[0][1]:
            print(f"Step = {step}, Shock params: {intensities[0], durations[0], frequency} applied to vehicle {shock_ids}\n")

            for controller in controllers:
                env.k.vehicle.set_max_speed(shock_ids[0], intensities[0])
                controller.set_shock_time(True)

            # Change color to magenta
            for i in shock_ids:
                env.unwrapped.k.vehicle.set_color(i, (255,0,255))

            current_duration_counter += 0.1

    # Do I need to return, yes for the counter to work
    return shock_counter, current_duration_counter, shock_ids 

def perform_shock(env, 
                shock_times, 
                step, 
                shock_counter, 
                current_duration_counter, 
                intensities, durations, 
                frequency, 
                shock_ids):
    """
    
    """

    controllers = [env.unwrapped.k.vehicle.get_acc_controller(i) for i in shock_ids]
    for controller in controllers:
        controller.set_shock_time(False)

    # len(durations) is the number of shocks.
    if shock_counter < len(durations) and current_duration_counter >= durations[shock_counter]:
        # reset the setup
        shock_counter += 1
        current_duration_counter = 0
        shock_ids = get_fresh_shock_ids(env)

    # Only apply shocks for a set number of times
    if shock_counter < frequency: # '<' because shock counter starts from zero
        if step >= shock_times[shock_counter][0] and step <= shock_times[shock_counter][1]:
            print(f"Step = {step}, Shock params: {intensities[shock_counter], durations[shock_counter], frequency} applied to vehicle {shock_ids}\n")

            for controller in controllers:
                controller.set_shock_accel(intensities[shock_counter])
                controller.set_shock_time(True)

            # Change color to magenta
            for i in shock_ids:
                env.unwrapped.k.vehicle.set_color(i, (255,0,255))

            current_duration_counter += 0.1 # increment current duration counter by one timestep seconds

    return shock_counter, current_duration_counter, shock_ids
 

def create_parser():
    """Create the parser to capture CLI arguments."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='[Flow] Evaluates a reinforcement learning agent '
                    'given a checkpoint.',
        epilog=EXAMPLE_USAGE)

    # required input parameters
    parser.add_argument(
        'result_dir', type=str, help='Directory containing results')
    parser.add_argument('checkpoint_num', type=str, help='Checkpoint number.')

    # optional input parameters
    parser.add_argument(
        '--run',
        type=str,
        help='The algorithm or model to train. This may refer to '
             'the name of a built-on algorithm (e.g. RLLib\'s DQN '
             'or PPO), or a user-defined trainable function or '
             'class registered in the tune registry. '
             'Required for results trained with flow-0.2.0 and before.')

    parser.add_argument(
        '--evaluate',
        action='store_true',
        help='Specifies whether to use the \'evaluate\' reward '
             'for the environment.')
    
    parser.add_argument('--method',type=str,default=None, help='Method name, can be [villarreal, ours]')

    return parser


if __name__ == '__main__':
    parser = create_parser()
    parser = update_arguments(parser)
    args = parser.parse_args()

    if args.method is None:
        raise ValueError("Method name must be specified")

    ray.init(num_cpus=1)
    visualizer_rllib(args)
