Created on top of snapshot of FLOW code obtained on Jan 3, 2023

### Installation instructions 

Developed and tested on Ubuntu 18.04.5 LTS, Python 3.7.3

- Install Anaconda
- Clone this repository
- Use the following commands

```
conda env create -f environment.yml
conda activate flow
python setup.py develop
pip install -U pip setuptools
```
Note: the requirements in this repo have redis version removed.
### Part 1: Training
```
python train.py --exp_config singleagent_ring
```

To view tensorboard while training: 
```
tensorboard --logdir=~/ray_results/
```

## Part 2: Generate rollouts from trained RL agent or using Classic controllers and save as csv files.
### RL agents:
Replace the method name to be one of: ours, wu

```
python test_rllib.py [Location of trained policy] [checkpoint number] --method wu --gen_emission --num_rollouts 10 --shock --render --length 260
```

### Classic controllers:
For all (replace the method_name to be one of: bcm, lacc, piws, fs, idm)
```
python classic.py --method [method_name] --render --length 260 --num_rollouts [no_of_rollouts] --shock --gen_emission
```

For stability tests where just the leader adds perturbations, include --stability to the lines above

## Part 3: Evaluate the generated rollouts

To evaluate the generated rollouts into Safety, Efficiency and Stability metrics:
Replace the method name to be one of: bcm, idm, fs, piws, lacc, wu, ours

```
python eval_metrics.py --method [method_name] --num_rollouts [no_of_rollouts]
```

To add plots to the metrics, include --save_plots

For Stability plots
```
python eval_plots.py --method [method_name]
```

-------------------------------------


## License

[MIT](https://choosealicense.com/licenses/mit/)

------------
Locations: 

./Ours/Trained_policies/Last_good/weak_accept_policy/PPO_DensityAwareRlEnv-v0_719f478a_2022-06-05_13-36-42okip6tqy 18

./Wu_et_al/Trained_policies/trained_here/PPO_WaveAttenuationPOEnv-v0_e2342e4c_2023-01-09_13-29-073it85esn 46

./Wu_et_al/Trained_policies/from_flow_code 200

Requirements have been modified 
