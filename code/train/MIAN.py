import sys
import math
import torch
import ctypes
import datetime
import numpy as np

from collections import Counter
from torch.autograd import Variable
from dataset import MIANDataSet
from torch.nn.functional import softmax
from torch.utils.data import DataLoader

FType = torch.FloatTensor
LType = torch.LongTensor

DID = 0

ctypes.cdll.LoadLibrary('caffe2_nvrtc.dll')


class MIAN:
    def __init__(self, directed=False):
        self.network = 'bitotc'
        self.file_path = '../../data/%s/%s.txt' % (self.network, self.network)
        self.emb_path = '../emb/%s/%s_MIAN_%d.emb'

        self.emb_size = 128
        self.neg_size = 10
        self.hist_len = 10
        self.lr = 0.001
        self.batch = 128
        self.save_step = 5
        self.epochs = 20
        # bitcoin/amazon epoch=5, dblp epoch=10, ml1m epoch=20
        self.layer_num = 1
        self.affect_threshold = 0.25
        # bitcoin/amazon=0.25, dblp=0.9, mllm=0.1

        self.data = MIANDataSet(self.file_path, self.neg_size, self.hist_len, self.emb_size, directed)

        self.node_dim = self.data.get_node_dim()
        self.first_time = self.data.get_first_time()
        self.node_list = self.data.get_node_list()

        if torch.cuda.is_available():
            with torch.cuda.device(DID):
                node_emb = MIAN.position_encoding_(self, self.node_list, self.emb_size)
                self.latest_emb = Variable(node_emb.cuda(), requires_grad=False)
                self.first_emb = Variable(node_emb.cuda(), requires_grad=False)
                self.active_emb = Variable(node_emb.cuda(), requires_grad=False)

                self.delta_a = Variable((torch.zeros(self.node_dim) + 1.).type(FType).cuda(), requires_grad=True)
                self.delta_a = MIAN.truncated_normal_(self.delta_a, tensor=(self.delta_a))
                self.delta_p = Variable((torch.zeros(self.node_dim) + 1.).type(FType).cuda(), requires_grad=True)
                self.delta_p = MIAN.truncated_normal_(self.delta_p, tensor=(self.delta_p))
                self.delta_t = Variable((torch.zeros(self.node_dim) + 1.).type(FType).cuda(), requires_grad=True)
                self.delta_t = MIAN.truncated_normal_(self.delta_t, tensor=(self.delta_t))

                self.w_node = Variable((torch.zeros(4, self.emb_size, self.emb_size) + 1.).type(FType).cuda(),
                                       requires_grad=True)
                self.w_node = MIAN.truncated_normal_(self.w_node, tensor=(self.w_node))
                self.w_neighbor = Variable((torch.zeros(4, self.emb_size, self.emb_size) + 1.).type(FType).cuda(),
                                           requires_grad=True)
                self.w_neighbor = MIAN.truncated_normal_(self.w_neighbor, tensor=(self.w_neighbor))
                self.w_network = Variable((torch.zeros(4, self.emb_size, self.emb_size) + 1.).type(FType).cuda(),
                                          requires_grad=True)
                self.w_network = MIAN.truncated_normal_(self.w_network, tensor=(self.w_network))
                self.b = Variable((torch.zeros(4, self.node_dim, self.emb_size) + 1.).type(FType).cuda(),
                                  requires_grad=True)
                self.b = MIAN.truncated_normal_(self.b, tensor=(self.b))

                self.hist_index = torch.arange(1, (self.hist_len + 1)).cuda()

                self.former_time = Variable((torch.zeros(self.node_dim) + self.first_time).type(FType).cuda(),
                                            requires_grad=False)

                self.active_flag = Variable(torch.zeros(self.node_dim).type(FType).cuda(), requires_grad=False)
                self.active_time = Variable((torch.zeros(self.node_dim) + self.first_time).type(FType).cuda(),
                                            requires_grad=False)
                self.zero_judgment = Variable(torch.zeros(1).type(FType).cuda(), requires_grad=False)

        else:
            node_emb = MIAN.position_encoding_(self, self.node_dim, self.emb_size)
            self.latest_emb = Variable(node_emb, requires_grad=False)
            self.first_emb = Variable(node_emb, requires_grad=False)
            self.active_emb = Variable(node_emb, requires_grad=False)

            self.delta_a = Variable((torch.zeros(self.node_dim) + 1.).type(FType).cuda(), requires_grad=True)
            self.delta_a = MIAN.truncated_normal_(self.delta_a, tensor=(self.delta_a))
            self.delta_p = Variable((torch.zeros(self.node_dim) + 1.).type(FType).cuda(), requires_grad=True)
            self.delta_p = MIAN.truncated_normal_(self.delta_p, tensor=(self.delta_p))
            self.delta_t = Variable((torch.zeros(self.node_dim) + 1.).type(FType).cuda(), requires_grad=True)
            self.delta_t = MIAN.truncated_normal_(self.delta_t, tensor=(self.delta_t))

            self.w_node = Variable((torch.zeros(4, self.emb_size, self.emb_size) + 1.).type(FType).cuda(),
                                   requires_grad=True)
            self.w_node = MIAN.truncated_normal_(self.w_node, tensor=(self.w_node))
            self.w_neighbor = Variable((torch.zeros(4, self.emb_size, self.emb_size) + 1.).type(FType).cuda(),
                                       requires_grad=True)
            self.w_neighbor = MIAN.truncated_normal_(self.w_neighbor, tensor=(self.w_neighbor))
            self.w_network = Variable((torch.zeros(4, self.emb_size, self.emb_size) + 1.).type(FType).cuda(),
                                      requires_grad=True)
            self.w_network = MIAN.truncated_normal_(self.w_network, tensor=(self.w_network))
            self.b = Variable((torch.zeros(4, self.node_dim, self.emb_size) + 1.).type(FType).cuda(),
                              requires_grad=True)
            self.b = MIAN.truncated_normal_(self.b, tensor=(self.b))

            self.hist_index = torch.arange(1, (self.hist_len + 1))

            self.former_time = Variable((torch.zeros(self.node_dim) + self.first_time).type(FType), requires_grad=True)

            self.active_flag = Variable(torch.zeros(self.node_dim).type(FType), requires_grad=False)
            self.active_time = Variable((torch.zeros(self.node_dim) + self.first_time).type(FType),
                                        requires_grad=False)
            self.zero_judgment = Variable(torch.zeros(1).type(FType), requires_grad=False)

        self.opt = torch.optim.Adam(lr=self.lr, params=[self.delta_a, self.delta_p, self.delta_t, self.w_node,
                                                        self.w_neighbor, self.w_network, self.b])
        self.scheduler = torch.optim.lr_scheduler.ExponentialLR(self.opt, gamma=0.98)

        self.loss = torch.FloatTensor()

    def position_encoding_(self, node_order, emb_size):
        print("Positional Encoding......")
        max_len = len(node_order)
        pe = torch.zeros(max_len, emb_size)
        node_emb = torch.zeros(max_len, emb_size)
        position = torch.arange(0, max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, emb_size, 2) * -(math.log(10000.0) / emb_size))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        i = 0
        for key in node_order.keys():
            node_order[key] = pe[i]
            i += 1
        for j in range(max_len):
            node_emb[j] = node_order[j]
        return pe

    def truncated_normal_(self, tensor, mean=0, std=0.09):
        with torch.no_grad():
            size = tensor.shape
            tmp = tensor.new_empty(size + (4,)).normal_()
            valid = (tmp < 2) & (tmp > -2)
            ind = valid.max(-1, keepdim=True)[1]
            tensor.data.copy_(tmp.gather(-1, ind).squeeze(-1))
            tensor.data.mul_(std).add_(mean)
            return tensor

    def the_GRU(self, s_nodes, node_emb, neighborhood_emb, network_emb):
        w_node = self.w_node  # [4, batch, batch]
        w_neighbor = self.w_neighbor
        w_network = self.w_network
        b = self.b.index_select(1, Variable(s_nodes.view(-1)))

        U_G = torch.sigmoid(torch.mm(node_emb, w_node[0]) + torch.mm(neighborhood_emb, w_neighbor[0]) +
                            torch.mm(network_emb, w_network[0]) + b[0])  # [batch, emb_size]
        R_G = torch.sigmoid(torch.mm(node_emb, w_node[1]) + torch.mm(neighborhood_emb, w_neighbor[1]) +
                            torch.mm(network_emb, w_network[1]) + b[1])
        G_G = torch.sigmoid(torch.mm(node_emb, w_node[2]) + torch.mm(neighborhood_emb, w_neighbor[2]) +
                            torch.mm(network_emb, w_network[2]) + b[2])
        tem_node_emb = torch.tanh(torch.mm(node_emb, w_node[3]) +
                                  torch.mul(R_G, torch.mm(neighborhood_emb, w_neighbor[3])) +
                                  torch.mul(G_G, torch.mm(network_emb, w_network[3]) + b[3]))
        new_node_emb = torch.mul((1 - U_G), node_emb) + torch.mul(U_G, tem_node_emb)

        return new_node_emb

    def active_status(self, s_nodes, s_cumulative_affinity, s_node_emb, t_times):
        flag_judgment = torch.eq(self.active_flag[s_nodes], self.zero_judgment) + 0  # [batch]
        affect_judgment = torch.gt(s_cumulative_affinity, self.affect_threshold) + 0  # [batch]
        status_judgment = torch.mul(flag_judgment, affect_judgment)
        self.active_flag[s_nodes] = self.active_flag[s_nodes] + status_judgment.data
        index = torch.nonzero(status_judgment, as_tuple=False).squeeze(-1)
        update_node = s_nodes[torch.nonzero(status_judgment, as_tuple=False)].squeeze(-1)
        self.active_emb[update_node] = s_node_emb[index].data
        self.active_time[update_node] = t_times[index].data

    def forward(self, s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask):

        batch = s_nodes.size()[0]

        s_node_emb = self.latest_emb.index_select(0, Variable(s_nodes.view(-1))).view(batch, -1)
        t_node_emb = self.latest_emb.index_select(0, Variable(t_nodes.view(-1))).view(batch, -1)
        h_node_emb = self.latest_emb.index_select(0, Variable(h_nodes.view(-1))).view(batch, self.hist_len, -1)
        n_node_emb = self.latest_emb.index_select(0, Variable(n_nodes.view(-1))).view(batch, self.neg_size, -1)
        h_time_mask = Variable(h_time_mask)  # [batch, hist_len]
        h_node_emb = torch.mul(h_node_emb, h_time_mask.unsqueeze(-1))

        delta_a = self.delta_a.index_select(0, Variable(s_nodes.view(-1)))
        delta_p = self.delta_p.index_select(0, Variable(s_nodes.view(-1))).unsqueeze(1)  # [batch_size, 1]
        delta_t = self.delta_t.index_select(0, Variable(s_nodes.view(-1))).unsqueeze(1)

        hist_index = self.hist_index

        former_time = self.former_time.index_select(0, Variable(s_nodes.view(-1)))
        first_emb = self.first_emb.index_select(0, Variable(s_nodes.view(-1))).view(batch, -1)
        first_time = torch.tensor(self.first_time).type(FType)

        # local neighborhood influence
        hist_len = h_time_mask.sum(dim=-1, keepdim=True)  # [batch,1]
        priority_weight = delta_p / (torch.mul(hist_index.unsqueeze(0), hist_len) + 1e-6)  # [batch, hist_len]

        affinity_per_neighbor = ((torch.sigmoid(
            torch.mul(s_node_emb.unsqueeze(1), h_node_emb).sum(
                dim=-1, keepdim=False)) / 2) + 0.5) * h_time_mask  # [batch, hist_len]
        affinity_sum = affinity_per_neighbor.sum(dim=-1, keepdim=True) + 1e-6
        affinity_weight = affinity_per_neighbor / affinity_sum  # [batch, hist_len]

        d_time = torch.abs(t_times.unsqueeze(1) - h_times)
        time_weight = torch.exp(delta_t * Variable(d_time))  # [batch, hist_len]

        neighborhood_param = (priority_weight * affinity_weight * time_weight * h_time_mask)

        neighborhood_emb = torch.mul(neighborhood_param.unsqueeze(-1),
                                     h_node_emb).sum(dim=1, keepdim=False)  # [batch, emb_size]

        s_cumulative_affinity = (torch.sigmoid(affinity_sum.squeeze(-1)) / 2) + 0.5  # [batch]
        self.active_status(s_nodes, s_cumulative_affinity, s_node_emb, t_times)
        active_flag = self.active_flag.index_select(0, Variable(s_nodes.view(-1))).view(batch, -1)  # [batch, 1]
        active_emb = self.active_emb.index_select(0, Variable(s_nodes.view(-1))).view(batch, -1)  # [batch, emb]
        active_time = self.active_time.index_select(0, Variable(s_nodes.view(-1))).view(batch, -1)  # [batch, 1]

        before_active_change = (active_emb - first_emb) / (active_time - first_time + 1e-6)
        after_active_change = (s_node_emb - active_emb) / (t_times.unsqueeze(-1) - active_time + 1e-6)
        network_change = torch.mul((after_active_change - before_active_change), active_time)
        network_weight = torch.mul(delta_a, (t_times - former_time + 1e-6))  # [batch]
        network_emb = torch.mul(active_flag, torch.mul(network_weight.unsqueeze(-1),
                                                       network_change))  # [batch,emb_size]

        for k in range(self.layer_num):
            s_node_emb = self.the_GRU(s_nodes, s_node_emb, neighborhood_emb, network_emb)  # [batch, emb_size]

        s_new_emb = s_node_emb

        p_lambda = ((s_new_emb - t_node_emb) ** 2).sum(dim=1).neg()
        n_lambda = ((s_new_emb.unsqueeze(1) - n_node_emb) ** 2).sum(dim=2).neg()

        self.former_time[s_nodes] = t_times.data

        return p_lambda, n_lambda, s_node_emb.data

    def loss_func(self, s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask):
        if torch.cuda.is_available():
            with torch.cuda.device(DID):
                p_lambdas, n_lambdas, new_node_emb = self.forward(s_nodes, t_nodes, t_times,
                                                                  n_nodes, h_nodes, h_times, h_time_mask)
                loss = -torch.log(p_lambdas.sigmoid() + 1e-6) - torch.log(n_lambdas.neg().sigmoid() + 1e-6).sum(dim=1)

        else:
            p_lambdas, n_lambdas, new_node_emb = self.forward(s_nodes, t_nodes, t_times,
                                                              n_nodes, h_nodes, h_times, h_time_mask)
            loss = -torch.log(torch.sigmoid(p_lambdas) + 1e-6) - torch.log(torch.sigmoid(torch.neg(n_lambdas)) + 1e-6).sum(dim=1)
        return loss

    def update(self, s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask):
        if torch.cuda.is_available():
            with torch.cuda.device(DID):
                self.opt.zero_grad()
                loss = self.loss_func(s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask)
                loss = loss.sum()
                self.loss += loss.data
                loss.backward()
                self.opt.step()
                self.sim_update_emb(s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask)

        else:
            self.opt.zero_grad()
            loss = self.loss_func(s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask)
            loss = loss.sum()
            self.loss += loss.data
            loss.backward()
            self.opt.step()
            self.sim_update_emb(s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask)

    def sim_update_emb(self,s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask):
        p_lambdas, n_lambdas, new_node_emb = self.forward(s_nodes, t_nodes, t_times, n_nodes, h_nodes, h_times, h_time_mask)

        self.latest_emb[s_nodes] = new_node_emb

    def train(self):
        print('Training......')
        for epoch in range(self.epochs):
            once_start = datetime.datetime.now()
            self.loss = 0.0
            loader = DataLoader(self.data, batch_size=self.batch, shuffle=True, num_workers=4)

            if epoch % self.save_step == 0 and epoch != 0:
                self.save_node_embeddings(self.emb_path % (self.network, self.network, epoch))

            for i_batch, sample_batched in enumerate(loader):
                if i_batch != 0:
                    sys.stdout.write('\r' + str(i_batch * self.batch) + '\tloss: ' + str(
                        self.loss.cpu().numpy() / (self.batch * i_batch)))
                    sys.stdout.flush()

                if torch.cuda.is_available():
                    with torch.cuda.device(DID):
                        self.update(sample_batched['source_node'].type(LType).cuda(),
                                    sample_batched['target_node'].type(LType).cuda(),
                                    sample_batched['target_time'].type(FType).cuda(),
                                    sample_batched['neg_nodes'].type(LType).cuda(),
                                    sample_batched['history_nodes'].type(LType).cuda(),
                                    sample_batched['history_times'].type(FType).cuda(),
                                    sample_batched['history_masks'].type(FType).cuda())

                else:
                    self.update(sample_batched['source_node'].type(LType),
                                sample_batched['target_node'].type(LType),
                                sample_batched['target_time'].type(FType),
                                sample_batched['neg_nodes'].type(LType),
                                sample_batched['history_nodes'].type(LType),
                                sample_batched['history_times'].type(FType),
                                sample_batched['history_masks'].type(FType))

            once_end = datetime.datetime.now()
            sys.stdout.write('\repoch ' + str(epoch) + ': avg loss = ' + str(self.loss.cpu().numpy() / len(self.data))
                             + '\tonce_runtime: ' + str(once_end - once_start) + '\n')
            sys.stdout.flush()
            self.scheduler.step()

        self.save_node_embeddings(self.emb_path % (self.network, self.network, self.epochs))

    def save_node_embeddings(self, path):
        if torch.cuda.is_available():
            embeddings = self.latest_emb.cpu().data.numpy()
        else:
            embeddings = self.latest_emb.data.numpy()
        writer = open(path, 'w')
        writer.write('%d %d\n' % (self.node_dim, self.emb_size))
        for n_idx in range(self.node_dim):
            writer.write(str(n_idx) + ' ' + ' '.join(str(d) for d in embeddings[n_idx]) + '\n')

        writer.close()


if __name__ == '__main__':
    start = datetime.datetime.now()
    MIAN = MIAN()
    MIAN.train()
    end = datetime.datetime.now()
    print('total runtime: %s' % str(end - start))