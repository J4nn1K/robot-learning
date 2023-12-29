"""
Based on Octo codebase (https://github.com/octo-models/octo/blob/main/examples/03_eval_finetuned.py)

This script demonstrates how to load and rollout a finetuned Octo model.

Modify the sys.path.append statement below to add the ACT repo to your path and start a virtual display:
    Xvfb :1 -screen 0 1024x768x16 &
    export DISPLAY=:1
"""

from absl import app, flags, logging
import gym
import jax
import numpy as np
import wandb
import mediapy

from octo.model.octo_model import OctoModel
from octo.utils.gym_wrappers import HistoryWrapper, RHCWrapper, UnnormalizeActionProprio


import sys
# add ACT to PATH for import
sys.path.append("./../act")
from sim_env import BOX_POSE, make_sim_env

sys.path.append("./envs")
from aloha_sim_env import AlohaGymEnv

FLAGS = flags.FLAGS

flags.DEFINE_string(
    "finetuned_path", None, "Path to finetuned Octo checkpoint directory."
)

flags.DEFINE_integer(
    "step", None, "If multiple checkpoints are present, which one to load."
)

# AlohaGymEnv()

gym.register(
    "aloha-sim-cube-v0",
    entry_point=lambda: AlohaGymEnv(
    make_sim_env("sim_transfer_cube"), camera_names=["top", "angle"]
    ),
)

def main(_):
    # setup wandb for logging
    # wandb.init(name="eval_aloha", project="octo-finetuning")

    # load finetuned model
    logging.info("Loading finetuned model...")
    model = OctoModel.load_pretrained(FLAGS.finetuned_path, FLAGS.step)

    env = gym.make("aloha-sim-cube-v0")

    # add wrappers for history and "receding horizon control", i.e. action chunking
    env = HistoryWrapper(env, horizon=1)
    env = RHCWrapper(env, exec_horizon=50)

    # wrap env to handle action/proprio normalization -- match normalization type to the one used during finetuning
    env = UnnormalizeActionProprio(
        env, model.dataset_statistics, normalization_type="normal"
    )

    # jit model action prediction function for faster inference
    policy_fn = jax.jit(model.sample_actions)

    # running rollouts
    for _ in range(1):
        obs, info = env.reset()

        # create task specification --> use model utility to create task dict with correct entries
        language_instruction = env.get_task()["language_instruction"]
        # print("INSTRUCTION: ", language_instruction)
        task = model.create_tasks(texts=language_instruction)

        # run rollout for 400 steps
        images = [obs["image_primary"][0]]
        images_angle = [obs["image_wrist"][0]]
        episode_return = 0.0
        while len(images) < 400:
            # model returns actions of shape [batch, pred_horizon, action_dim] -- remove batch
            actions = policy_fn(
                jax.tree_map(lambda x: x[None], obs), task, rng=jax.random.PRNGKey(0)
            )
            actions = actions[0]

            # step env -- info contains full "chunk" of observations for logging
            # obs only contains observation for final step of chunk
            obs, reward, done, trunc, info = env.step(actions)
            images.extend([o["image_primary"][0] for o in info["observations"]])
            images_angle.extend([o["image_wrist"][0] for o in info["observations"]])
            episode_return += reward
            if done or trunc:
                break
        
        print(f"Episode return: {episode_return}")

        # log rollout video to wandb -- subsample temporally 2x for faster logging
        # wandb.log(
        #     {"rollout_video": wandb.Video(np.array(images).transpose(0, 3, 1, 2)[::2])}
        # )
        # wandb.log(
        #     {"rollout_video": wandb.Video(np.array(images).transpose(0, 3, 1, 2)[10:], 30)}
        # )
        
        np.save(f"export/raw/episode{_+1}.npy", np.array(images)[10:])
        np.save(f"export/raw/episode{_+1}_angle.npy", np.array(images_angle)[10:])
        
        mediapy.write_video(f"export/raw/video{_+1}.gif", np.array(images_angle)[10:], fps=30, codec='gif')
        
    


if __name__ == "__main__":
    app.run(main)