"""AutoencoderTrainer class.

AutoencoderTrainer is a class to support training of torch models
as an AutoEncoder.

It provides functions to train, validate, save and test the model
while keeping track of its losses along epochs.
"""


# TODO:
# - [ ] save separated checkpoint for each successful validation
# - [ ] add specific error texts for:
#     - [ ] output dimensions not matching the expected (== input dimensions)
#     - [ ] train, valid and test dataset are not properly loaded
# 
# TO TEST:
# - [ ] calculate validation before training if loss_valid_best is Infinite (to avoid always saving first trained model)
# - [ ] throw warning if max_epochs_total < max_epochs_without_valid
# - [x] create run function that executes run_epochs until failed validated after max_epochs
# - [x] add kwarg path to output saved model (ie: path_output = './models/checkpoint.pth')
# - [x] store losses across epochs for plot


import warnings
import torch
from torchvision import datasets
import torchvision.transforms as transforms
import torch.nn as nn
import torch.nn.functional as F
from collections import defaultdict
from torch.utils.data import Dataset, DataLoader
import matplotlib.pyplot as plt


class RMSELoss(nn.Module):
    """Creates a criterion that measures the root mean squared error (root squared L2 norm)
    between each element in the input yhat and target y.
    """
    
    def __init__(self):
        super().__init__()
        self.mse = nn.MSELoss()
        
    def forward(self, yhat, y):
        return torch.sqrt(self.mse(yhat, y))



class AddGaussianNoise(object):
    """Adds a gaussian normal noise to the input tensor."""
    
    def __init__(self, mean=0., std=1.):
        self.std = std
        self.mean = mean
        
    def __call__(self, tensor):
        return tensor + torch.randn(tensor.size()) * self.std + self.mean
    
    def __repr__(self):
        return self.__class__.__name__ + '(mean={0}, std={1})'.format(self.mean, self.std)



class AutoencoderTrainer(object):
    """AutoEncoder Trainer for torch model."""
    
    transform = [] #: (torch transforms, optional): Transformations to be applied across all dataset (train, valid and test).
    noise_transform = AddGaussianNoise() #: (torch function, default AddGaussianNoise): Function used to add noise to the clear data.
    criterion = RMSELoss() #: (torch function, default RMSELoss): Criterion function to calculate the loss.
    dataset = dict() #: (dict of Dataset): Dictionary containing the train, valid and test dataset.
    loader = dict() #: (torch DataLoader, optional): data loader used to iterate over train, valid and test dataset.
    batch_size = 20 #: (int, default 20): batch size to slice dataset while calculating the loss.
    num_workers = 0 #: (int, default 0): number of parallel processes.
    path_test = None #: (str or list of str): paths to the test dataset.
    path_train = None #: (str or list of str): paths to the training dataset.
    path_valid = None #: (str or list of str): paths to the validation dataset.
    dataset_class = Dataset #: (torch Dataset, optional): class used to instantiate train, valid and test Dataset.
    save_file = 'checkpoint.pth' #: (str): path and filename to save the model everytime we have a new lowest validation loss.
    loss_valid_best = float("Inf") #: (float, default Inf): initial validation loss.
    optimizer_function = torch.optim.Adam #: (torch optim, default Adam): optimizer function to calculate optimum weights correction.
    optimizer_kwargs = {'lr': 0.0001} #: (optimizer kwrags, default {'lr': 0.0001}): optimizer kwrags parameters.
    epoch = 0 #: (int, default 0): initial epoch.
    loss_valid = dict() #: (dict): validation loss for each epoch.
    loss_train = dict() #: (dict): training loss for each epoch.
    valid_epochs = [] #: (list of int): epochs which the validation loss reached its new lowest record value.
    
    
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
           
        self._create_dataset()
            
        for dataset_type, dataset in self.dataset.items():
            self.loader[dataset_type] = self._create_loader(dataset)
            
        
        self.train_on_gpu = torch.cuda.is_available()
        if self.train_on_gpu: self.model.to('cuda')
            
        
        self.optimizer = self.optimizer_function(self.model.parameters(), **self.optimizer_kwargs)
        
        self.loss_valid_best = self._loss(self.loader['valid'])
            
            
    def _create_dataset(self):
        for dataset_type in ['train', 'test', 'valid']:
            path = getattr(self, 'path_' + dataset_type)
            if path is None:
                raise ValueError('Missing path to', dataset_type, 'dataset.')
            else:
                self.dataset[dataset_type] = self.dataset_class(root=path, transform=self.transform)
                        
            
    def _create_loader(self, dataset):
        return torch.utils.data.DataLoader(dataset, batch_size=self.batch_size, num_workers=self.num_workers)
    
    
    def best_model(self):
        """Returns the torch model with the lowest validation loss."""
        return torch.load(self.save_file)
    
    
    def last_model(self):
        """Returns the last trained torch model (which is unlikely the lowest validation loss)."""
        return self.model
        
        
    def _loss(self, loader=None, backpropagate=False):
        """Calculates the noised and denoised losses on the whole 'loeader' dataset.

        Args:
            loader (torch DataLoader): Dataset used to calculate the loss.
            backpropagate (bool, default False): Condition to backpropagate the loss in order to train the model."""

        loss = 0
        
        if loader is None: loader = self.loader
            
        samples = len(loader)
        
        if backpropagate:
            self.model.train()
        else:            
            self.model.eval()
            
        if self.train_on_gpu: self.model = self.model.cuda()

        for data in loader:

            # _ stands in for labels
            x, _ = data

            ## add random noise to the input
            x_noised = self.noise_transform(x.clone())

            if self.train_on_gpu: x, x_noised = x.cuda(), x_noised.cuda()
                
                
            if backpropagate: self.optimizer.zero_grad()

            ## forward pass: compute predicted outputs by passing *noisy* inputs to the model
            x_denoised = self.model(x_noised)
                    
            loss_batch = self.criterion(x_denoised, x)  

            if backpropagate:
                # backward pass: compute gradient of the loss with respect to model parameters
                loss_batch.backward()
                # perform a single optimization step (parameter update)
                self.optimizer.step()
                
            # update cumulated loss
            loss += loss_batch.item()
            
                
        # normalize loss per sample size
        loss /= samples
                
            
        return loss
    
    
    def train(self):
        """Trains the model on the whole train dataset.

        Returns:
            float: Training loss.
        """             
        return self._loss(self.loader['train'], backpropagate=True) 
    
    
    def test(self):
        """Calculates the loss on the whole test dataset.

        Returns:
            float: Test loss.
        """            
        return self._loss(self.loader['test'])
    
    
    def validate(self):
        """Calculates the loss on the whole validation dataset
        and persistently saves model if this loss decreased.

        Returns:
            float: Validation loss.
            bool: True if found the lowest validation loss.
        """
        loss_valid = self._loss(self.loader['valid'])
        is_validated = (loss_valid < self.loss_valid_best)
        if loss_valid < self.loss_valid_best:
            self.loss_valid_best = loss_valid
            torch.save(self.model, self.save_file)
            
        return loss_valid, is_validated
    
    
    def _print_header(self):
        print('Epoch \t Training Loss \t Validation Loss \t Saved ')
    
    
    def _print_statistics(self, epoch, saved_model=False):
        print(' {} \t {:.7f} \t {:.7f} \t\t {}'.format(
            self.epoch,
            self.loss_train[epoch],
            self.loss_valid[epoch],
            u'\u2713' if saved_model else '',
            ))
    
    
    def run_epochs(self, epochs=1, *, verbose=True, verbose_header=True):
        """Runs train and validation for a fixed amount of epochs.

        Args:
            epochs (int, default 1): Exact amount of epochs to run the train loop.
            verbose (bool, default True): Condition to print losses along the epochs.
            verbose_header (bool, default True): Condition to print the header before printing the losses.
        """

        if (verbose) and (verbose_header): self._print_header()

        for epoch in range(self.epoch, self.epoch + epochs):
            self.loss_train[epoch] = self.train()
            self.loss_valid[epoch], is_validated = self.validate()
            if is_validated: self.valid_epochs.append(epoch)
            
            if verbose: self._print_statistics(epoch, is_validated)
            
            self.epoch += 1
                
                
        return self.best_model()
    
    
    
    def run(self, *, max_epochs_total=1000, max_epochs_without_valid=100, verbose=True):
        """Runs train until reached maximum amount of epochs without better validation loss.

        Args:
            max_epochs_total (int, default 1000): Maximum epochs to run before leaving the train loop.
            max_epochs_without_valid (int, default 100): Maximum epochs to run without decrease of the best validation loss.
            verbose (bool, default True): Condition to print losses along the epochs.

        Returns:
            torch Module: AutoEncoder torch model with the lowest validation loss.
        """
        
        if max_epochs_total < max_epochs_without_valid:
            warnings.warn(f'It will execute all "max_epochs_without_valid" ({max_epochs_without_valid}) epochs because it is defined as a number greater than "max_epochs_total" ({max_epochs_total}).')

        if verbose: self._print_header()
            
        epoch_last_valid = self.epoch
        
        reached_max_without_valid = False
            
        for epoch in range(self.epoch, self.epoch + max_epochs_total):
            self.run_epochs(1, verbose_header=False)
            is_validated = (epoch in self.valid_epochs)
            if is_validated: epoch_last_valid = epoch
            
            reached_max_without_valid = (epoch - epoch_last_valid > max_epochs_without_valid)
            if reached_max_without_valid:
                print('Best model found.')
                break                
                
                
        if not reached_max_without_valid:
            print('Best mode not found because "run" finished too early. Consider increasing "max_epochs_total" argument and executing "run" again.')
                
                
        return self.best_model()
    
    
    def plot_losses(self):
        """Plots the train and validation losses along epochs, including saved checkpoints."""
        for loss_type in ('train', 'valid'):
            loss_dict = getattr(self, 'loss_' + loss_type)
            plt.plot(list(loss_dict.keys()),
                     list(loss_dict.values()),
                    label=loss_type)

        plt.scatter(trainer.valid_epochs,
                 [loss_dict[e] for e in trainer.valid_epochs],
                 label='saved', c='r')

        plt.legend()
        plt.xlabel('epochs')
        plt.ylabel('loss')
        plt.gcf().patch.set_facecolor('white')
        plt.tight_layout()