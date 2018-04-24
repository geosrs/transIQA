import torch
import numpy as np
from model import Net_deep
import tools
import argparse
from torch.autograd import Variable
import torch.nn.functional as F
import copy

'''
Fine-tune on LIVE dataset

Refer main.py
1. load_model
2. get dataloader
3. train
4. test
'''

parser = argparse.ArgumentParser(description='fine-tune exist model on LIVE.')

parser.add_argument('--limited', action='store_true',
                    help='run with 8G memory pc')
parser.add_argument('--load_model', type=str, default='./model/cuda_True_epoch_550',
                    help='model path to fine-tune from')
parser.add_argument('--epochs', type=int, default=5000,
                    help='[5000]total epochs of training')
parser.add_argument('--lr', type=float, default=1e-5,
                    help='[1e-5] learning rate')
parser.add_argument('--optimizer', type=str, default='adam',
                    help='[adam] optimizer type')
parser.add_argument('--train_loss', type=str, default='mae',
                    help='[mae] training loss function')
parser.add_argument('--test_loss', type=str, default='mae',
                    help='[mae] testing loss function')
parser.add_argument('--data_log', type=str, default='',
                    help='['']path to write data for visualization')
parser.add_argument('--model_reload', type=str, default='',
                    help='['']path to reload model')
parser.add_argument('--epoch_reload', type=int, default=0,
                    help='[0]epoch when reloaded model finished')
parser.add_argument('--model_save', type=str, default='',
                    help='['']model saving path')
parser.add_argument('--model_epoch', type=int, default=1000,
                    help='[1000]epochs for saving the best model')
args = parser.parse_args()


epochs = args.epochs
optimizer = args.optimizer
lr = args.lr
train_loss = args.train_loss
test_loss = args.test_loss
data_log = args.data_log
model_reload = args.model_reload
epoch_reload = args.epoch_reload
model_save = args.model_save
model_epoch = args.model_epoch
write_data = True if data_log != '' \
    else False
reload = True if model_reload != '' and epoch_reload != 0 \
    else False
model_path = args.load_model if not reload \
    else args.model_reload
save_model = True if model_save != '' \
    else False

batch_size = 32
num_workers = 4
cuda = torch.cuda.is_available()
live_train = './data/live_generator/ft_live_train.txt'
live_test = './data/live_generator/ft_live_test.txt'

# if model_path == '', train from scratch
model = torch.load(model_path) if model_path != '' \
    else Net_deep()
if cuda:
    model.cuda()
if save_model:
    best_model = {'model': None,
                  'epoch': -1,
                  'loss': -1,
                  'lcc': -1,
                  'srocc': -1,
                  'new': False}

optimizer = torch.optim.Adam(model.parameters(), lr=lr, betas=(0.9, 0.99))

live_dataset = tools.get_live_dataset(live_train=live_train,
                                      live_test=live_test)
data_loader = tools.get_dataloader(live_dataset,
                                   batch_size=batch_size,
                                   shuffle=True,
                                   num_workers=num_workers)


def train(epoch=1):
    model.train()

    for batch_idx, sample_batched in enumerate(data_loader):
        image = sample_batched['image']
        score = sample_batched['score']

        if cuda:
            image, score = image.cuda(), score.cuda()
        image, score = Variable(image), Variable(score)

        optimizer.zero_grad()
        output = model(image)
        if train_loss == 'mse':
            loss = F.mse_loss(output, score)
        elif train_loss == 'mae':
            loss = F.l1_loss(output, score)
        else: exit(0)
        loss.backward()
        optimizer.step()

    tools.log_print('Epoch_{} Loss: {:.2f}'.format(
        epoch, loss.data[0]))
    lcc, srocc = tools.evaluate_on_metric(output, score)

    if write_data:
        with open(data_log, 'a') as f:

            line = 'train epoch:{} percent:{:.6f} loss:{:.4f} lcc:{:.4f} srocc:{:.4f}\n'
            line = line.format(epoch,
                               0.,
                               loss.data[0],
                               lcc,
                               srocc)
            f.write(line)


def test(epoch):
    model.eval()

    images = live_dataset.test_images
    scores = live_dataset.test_scores
    outputs = []

    for i in range(len(images)):

        image = images[i]
        height = image.shape[0]
        width = image.shape[1]

        patches = []
        for i in range(30): # num of small patch
            top = np.random.randint(0, height - 32)
            left = np.random.randint(0, width - 32)
            patches.append(image[top:top+32, left:left+32, :].transpose((2, 0, 1)))

        patches = np.array(patches)
        #debug
        debug=0
        if debug:
            print(patches)
            print(patches.shape)
        patches = torch.from_numpy(patches)

        if cuda:
            patches = patches.cuda()
        patches = Variable(patches)

        output = model(patches).data
        output = sum(output) / 30
        outputs.append(output)

    if test_loss == 'mse':
        loss = np.mean((np.array(outputs - scores)) ** 2)
    elif test_loss == 'mae':
        loss = np.mean(np.abs(np.array(outputs - scores)))
    tools.log_print('TESTING LOSS:{:.6f}'.format(loss))
    lcc, srocc = tools.evaluate_on_metric(outputs, scores)

    if write_data:
        with open(data_log, 'a') as f:
            f.write('test loss:{:.4f} lcc:{:.4f} srocc:{:.4f}\n'.format(loss, lcc, srocc))

    # save best model
    if save_model and srocc > best_model['srocc'] and lcc > best_model['lcc']:
        best_model['model'] = copy.deepcopy(model)
        best_model['epoch'] = epoch
        best_model['loss'] = loss.data[0]
        best_model['lcc'] = lcc
        best_model['srocc'] = srocc
        # update 'new' buffer
        best_model['new'] = True


print('Logging data info to: {}'.format(data_log))
print(args)
print(model)
if write_data:
    with open(data_log, 'a') as f:
        f.write(str(args) + '\n')
        f.write(str(model) + '\n')

for i in range(epochs):
    epoch = i + 1 + epoch_reload

    test(epoch)
    train(epoch)

    if i % model_epoch == 0 and best_model['new'] == True:
        path = model_save + '_{}_{:.4f}_{:.4f}'.format(
            best_model['epoch'], best_model['lcc'], best_model['srocc'])
        tools.log_print('Saving model:{}'.format(path))
        torch.save(best_model['model'], path)
        # close buffer
        best_model['new'] = False