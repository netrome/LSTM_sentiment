import sys

import torch
from torch.utils.data import DataLoader
from torch.autograd import Variable
from visdom import Visdom
import numpy as np

import datasets
import settings
import models
import utils


def my_collate(batch):
    '''Collates list of samples to minibatch'''

    batch = sorted(batch, key=lambda item: -len(item[0]))
    features = [i[0] for i in batch]
    targets = torch.stack([i[1] for i in batch])

    features = utils.pack_sequence(features)
    features, lengths = torch.nn.utils.rnn.pad_packed_sequence(features, padding_value=0)

    return features, lengths, targets



# Instansiate dataset
dataset = settings.DATASET(settings.args.data_path, **settings.DATA_KWARGS)
data_loader = DataLoader(dataset, batch_size=settings.BATCH_SIZE, shuffle=True, num_workers=1, collate_fn=my_collate)

# Define model and optimizer
model = utils.generate_model_from_settings()
optimizer = torch.optim.Adam(model.parameters(), lr=settings.LEARNING_RATE)

# Visualization thorugh visdom
viz = Visdom()
loss_plot = viz.line(X=np.array([0]), Y=np.array([0]), opts=dict(showlegend=True, title="Loss"))
hist_opts = settings.HIST_OPTS
hist_opts["title"] = "Predicted star distribution"
dist_hist = viz.bar(X=np.array([0, 0, 0]), opts=dict(title="Predicted stars"))
real_dist_hist = viz.bar(X=np.array([0, 0, 0]))

# Move stuff to GPU
if settings.GPU:
    data_loader.pin_memory = True
    model.cuda()

#Values for visualization
smooth_loss = 7 #approx 2.5^2
decay_rate = 0.99
smooth_real_dist = np.array([0, 0, 0, 0, 0], dtype=float)
smooth_pred_dist = np.array([0, 0, 0, 0, 0], dtype=float)

counter = 0
for epoch in range(settings.EPOCHS):
    # Stars for histogram
    stars = np.zeros(len(dataset))

    # Main epoch loop
    length = len(dataset)/settings.BATCH_SIZE
    print("Starting epoch {} with length {}".format(epoch, length))
    for i, (feature, lengths, target) in enumerate(data_loader):
        if settings.GPU:
            feature = feature.cuda(async=True)
            target = target.cuda(async=True)

        out = model(feature, lengths)

        # Loss computation and weight update step
        loss = torch.mean((out - target)**2)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # Visualization update
        stars[i] = torch.mean(out[0, :, 0])
        smooth_loss = smooth_loss * decay_rate + (1-decay_rate) * loss.data.cpu().numpy()
        viz.updateTrace(win=loss_plot, X=np.array([counter]), Y=loss.data.cpu().numpy(), name='loss')
        viz.updateTrace(win=loss_plot, X=np.array([counter]), Y=smooth_loss, name='smooth loss')
        real_star = target[:, 0].data.cpu().numpy().astype(int)
        pred_star = out[0, :, 0].data.cpu().numpy().round().clip(1,5).astype(int)
        for idx in range(len(real_star)):
            smooth_pred_dist[pred_star[idx]-1] += 1
            smooth_real_dist[real_star[idx]-1] += 1
        smooth_real_dist *= decay_rate
        smooth_pred_dist *= decay_rate


        viz.bar(win=dist_hist, X=smooth_pred_dist)
        viz.bar(win=real_dist_hist, X=smooth_real_dist)

        counter += 1

        # Progress update
        if i % 10 == 0:
            sys.stdout.write("\rIter {}/{}, loss: {}".format(i, length, float(loss)))
    print("Epoch finished with last loss: {}".format(float(loss)))

    # Visualize distribution and save model checkpoint
    #viz.histogram(win=dist_hist, X=stars, opts=hist_opts)
    name = "{}_epoch{}.params".format(model.get_name(), epoch)
    utils.save_model_params(model, name)
    print("Saved model params as: {}".format(name))



