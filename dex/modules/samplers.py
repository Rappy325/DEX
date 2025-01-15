from ..utils.general_utils import AttrDict, listdict2dictlist
from ..utils.rl_utils import ReplayCache

import os
import torch
import numpy as np
import PIL.Image as Image

from cleandiffuser.dataset.Surrol_dataset import SurrolDataset

class Sampler:
    """Collects rollouts from the environment using the given agent."""
    def __init__(self, env, agent, max_episode_len):
        self._env = env
        self._agent = agent
        self._max_episode_len = max_episode_len

        self._obs = None
        self._episode_step = 0
        self._episode_cache = ReplayCache(max_episode_len)
        self._device = torch.device(
            'cuda:' + str(0)
            if torch.cuda.is_available() else 'cpu'
        )

    def init(self):
        """Starts a new rollout. Render indicates whether output should contain image."""
        self._episode_reset()

    def sample_action(self, obs, is_train):
        return self._agent.get_action(obs, noise=is_train)
    
    def sample_episode(self, is_train, render=False, random_act=False):
        """Samples one episode from the environment."""
        self.init()
        episode, done = [], False

        solver = "ddpm"
        sampling_step = 5
        num_envs = 1
        act_dim = 5

        task = "NeedlePick"
        dataset = SurrolDataset("/bd_byta6000i0/users/jhun/DEX2/trained_diffusion_models/" + task + "-v0/data_NeedlePick-v0_random_100.npz", horizon=5, pad_before=2, pad_after=2)
        # print(dataset[0]['obs']['state'][0])
        # print(len(dataset[0]['obs']['state'][0]))
        normalizers = dataset.get_normalizer()
        state_normalizer = normalizers["obs"]["state"]
        action_normalizer = normalizers["action"]
        # print(f"length of state_normalizer: {len(state_normalizer.max)}")

        obs, done, _, _ = self._env.reset(), False, 0., 0
        # print(obs)
        prior = torch.zeros((num_envs, act_dim), device=self._device)
        
        while not done and self._episode_step < self._max_episode_len:
            # action = self._env.action_space.sample(
            # ) if random_act else self.sample_action(self._obs, is_train) 

            ## write my own action(generated by model)
            
            # generate action
            if random_act:
                action = self._env.action_space.sample() 
            else:  
                obs1 = state_normalizer.normalize(np.hstack((obs['observation'],obs['desired_goal'])))
                obs_np = np.array([obs1])
                # print(obs)
                # print(obs_np.shape, obs_np)
                # obs_torch = torch.from_numpy(obs)
                # obs_torch = obs_torch.to(torch.get_default_dtype()) 

                action, _ = self._agent.sample(
                        prior, solver=solver, n_samples=1, sample_steps=sampling_step,
                        sample_step_schedule="quad_continuous",
                        w_cfg=1.0, condition_cfg=torch.tensor(obs_np, device=self._device, dtype=torch.float32))
                action = action.cpu().numpy()
                action = action_normalizer.unnormalize(action)

                # print(f"shape of action generated: {action}")
                # print(action.shape)
                # print(np.squeeze(action))


            ########################
            if action is None:
                break
            if render:
                render_obs = self._env.render('rgb_array') 
            

            obs, reward, _done, info = self._env.step(np.squeeze(action))
            episode.append(AttrDict(
                reward=reward,
                success=info['is_success'],
                info=info
            ))
            self._episode_cache.store_transition(obs, action, _done)
            if render:
                episode[-1].update(AttrDict(image=render_obs))

            # update stored observation
            self._obs = obs
            self._episode_step += 1

        episode[-1].done = True     # make sure episode is marked as done at final time step
        rollouts = self._episode_cache.pop()
        assert self._episode_step == self._max_episode_len
        return listdict2dictlist(episode), rollouts, self._episode_step

    def _episode_reset(self, global_step=None):
        """Resets sampler at the end of an episode."""
        self._episode_step, self._episode_reward = 0, 0.
        self._obs = self._reset_env()
        self._episode_cache.store_obs(self._obs)

    def _reset_env(self):
        return self._env.reset()