# This file is part of PyEMMA.
#
# Copyright (c) 2017 Computational Molecular Biology Group, Freie Universitaet Berlin (GER)
#
# PyEMMA is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""
@author: paul
"""

from __future__ import absolute_import
import unittest
import numpy as np
from pyemma.coordinates import vamp as pyemma_api_vamp
from pyemma.msm import estimate_markov_model
from logging import getLogger

logger = getLogger('pyemma.'+'TestVAMP')


def random_matrix(n, rank=None, eps=0.01):
    m = np.random.randn(n, n)
    u, s, v = np.linalg.svd(m)
    if rank is None:
        rank = n
    if rank > n:
        rank = n
    s = np.concatenate((np.maximum(s, eps)[0:rank], np.zeros(n-rank)))
    return u.dot(np.diag(s)).dot(v)


class TestVAMPSelfConsistency(unittest.TestCase):
    def test_full_rank(self):
        self.do_test(20, 20, test_partial_fit=True)

    def test_low_rank(self):
        dim = 30
        rank = 15
        self.do_test(dim, rank, test_partial_fit=True)

    def do_test(self, dim, rank, test_partial_fit=False):
        # setup
        N_frames = [123, 456, 789]
        N_trajs = len(N_frames)
        A = random_matrix(dim, rank)
        trajs = []
        mean = np.random.randn(dim)
        for i in range(N_trajs):
            # set up data
            white = np.random.randn(N_frames[i], dim)
            brown = np.cumsum(white, axis=0)
            correlated = np.dot(brown, A)
            trajs.append(correlated + mean)

        # test
        tau = 50
        vamp = pyemma_api_vamp(trajs, lag=tau, scaling=None)
        vamp.right = True

        assert vamp.dimension() <= rank

        atol = np.finfo(vamp.output_type()).eps*10.0
        phi_trajs = [ sf[tau:, :] for sf in vamp.get_output() ]
        phi = np.concatenate(phi_trajs)
        mean_right = phi.sum(axis=0) / phi.shape[0]
        cov_right = phi.T.dot(phi) / phi.shape[0]
        np.testing.assert_allclose(mean_right, 0.0, atol=atol)
        np.testing.assert_allclose(cov_right, np.eye(vamp.dimension()), atol=atol)

        vamp.right = False
        psi_trajs = [ sf[0:-tau, :] for sf in vamp.get_output() ]
        psi = np.concatenate(psi_trajs)
        mean_left = psi.sum(axis=0) / psi.shape[0]
        cov_left = psi.T.dot(psi) / psi.shape[0]
        np.testing.assert_allclose(mean_left, 0.0, atol=atol)
        np.testing.assert_allclose(cov_left, np.eye(vamp.dimension()), atol=atol)

        # compute correlation between left and right
        assert phi.shape[0]==psi.shape[0]
        C01_psi_phi = psi.T.dot(phi) / phi.shape[0]
        n = max(C01_psi_phi.shape)
        C01_psi_phi = C01_psi_phi[0:n,:][:, 0:n]
        np.testing.assert_allclose(C01_psi_phi, np.diag(vamp.singular_values[0:vamp.dimension()]), atol=atol)

        if test_partial_fit:
            vamp2 = pyemma_api_vamp(lag=tau, scaling=None)
            for t in trajs:
                vamp2.partial_fit(t)

            model_params = vamp._model.get_model_params()
            model_params2 = vamp2._model.get_model_params()

            for n in model_params.keys():
                if model_params[n] is not None and model_params2[n] is not None:
                    np.testing.assert_allclose(model_params[n], model_params2[n])

            vamp2.singular_values # trigger diagonalization

            vamp2.right = True
            for t, ref in zip(trajs, phi_trajs):
                np.testing.assert_allclose(vamp2.transform(t[tau:]), ref)

            vamp2.right = False
            for t, ref in zip(trajs, psi_trajs):
                np.testing.assert_allclose(vamp2.transform(t[0:-tau]), ref)


def generate(T, N_steps, s0=0):
    dtraj = np.zeros(N_steps, dtype=int)
    s = s0
    T_cdf = T.cumsum(axis=1)
    for t in range(N_steps):
        dtraj[t] = s
        s = np.searchsorted(T_cdf[s, :], np.random.rand())
    return dtraj


def assert_allclose_ignore_phase(A, B, atol):
    A = np.atleast_2d(A)
    B = np.atleast_2d(B)
    assert A.shape == B.shape
    for i in range(B.shape[1]):
        assert np.allclose(A[:, i], B[:, i], atol=atol) or np.allclose(A[:, i], -B[:, i], atol=atol)


class TestVAMPCKTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        N_steps = 10000
        N_traj = 2
        lag = 1
        T = np.linalg.matrix_power(np.array([[0.7, 0.2, 0.1], [0.1, 0.8, 0.1], [0.1, 0.1, 0.8]]), lag)
        dtrajs = [generate(T, N_steps) for _ in range(N_traj)]
        p0 = np.zeros(3)
        p1 = np.zeros(3)
        trajs = []
        for dtraj in dtrajs:
            traj = np.zeros((N_steps, T.shape[0]))
            traj[np.arange(len(dtraj)), dtraj] = 1.0
            trajs.append(traj)
            p0 += traj[:-lag, :].sum(axis=0)
            p1 += traj[lag:, :].sum(axis=0)
        vamp = pyemma_api_vamp(trajs, lag=lag, scaling=None)
        msm = estimate_markov_model(dtrajs, lag=lag, reversible=False)
        cls.dtrajs = dtrajs
        cls.lag = lag
        cls.msm = msm
        cls.vamp = vamp
        cls.p0 = p0 / p0.sum()
        cls.p1 = p1 / p1.sum()

    def test_K_is_T(self):
        m0 = self.vamp.model.mean_0
        mt = self.vamp.model.mean_t
        C0 = self.vamp.model.C00 + m0[:, np.newaxis]*m0[np.newaxis, :]
        C1 = self.vamp.model.C0t + m0[:, np.newaxis]*mt[np.newaxis, :]
        K = np.linalg.inv(C0).dot(C1)
        np.testing.assert_allclose(K, self.msm.P, atol=1E-5)

        Tsym = np.diag(self.p0 ** 0.5).dot(self.msm.P).dot(np.diag(self.p1 ** -0.5))
        np.testing.assert_allclose(np.linalg.svd(Tsym)[1][1:], self.vamp.singular_values[0:2], atol=1E-7)

    def test_singular_functions_against_MSM(self):
        Tsym = np.diag(self.p0 ** 0.5).dot(self.msm.P).dot(np.diag(self.p1 ** -0.5))
        Up, S, Vhp = np.linalg.svd(Tsym)
        Vp = Vhp.T
        U = Up * (self.p0 ** -0.5)[:, np.newaxis]
        V = Vp * (self.p1 ** -0.5)[:, np.newaxis]
        assert_allclose_ignore_phase(U[:, 0], np.ones(3), atol=1E-5)
        assert_allclose_ignore_phase(V[:, 0], np.ones(3), atol=1E-5)
        U = U[:, 1:]
        V = V[:, 1:]
        self.vamp.right = True
        phi = self.vamp.transform(np.eye(3))
        self.vamp.right = False
        psi = self.vamp.transform(np.eye(3))
        assert_allclose_ignore_phase(U, psi, atol=1E-5)
        assert_allclose_ignore_phase(V, phi, atol=1E-5)
        references_sf = [U.T.dot(np.diag(self.p0)).dot(np.linalg.matrix_power(self.msm.P, k*self.lag)).dot(V) for k in
                         range(10-1)]
        cktest = self.vamp.cktest(n_observables=2, mlags=10)
        pred_sf = cktest.predictions
        esti_sf = cktest.estimates
        for e, p, r in zip(esti_sf[1:], pred_sf[1:], references_sf[1:]):
            np.testing.assert_allclose(np.diag(p), np.diag(r), atol=1E-5)
            np.testing.assert_allclose(np.abs(p), np.abs(r), atol=1E-4)

    def test_CK_expectation_against_MSM(self):
        obs = np.eye(3) # observe every state
        cktest = self.vamp.cktest(observables=obs, statistics=None, mlags=4)
        pred = cktest.predictions[1:]
        est = cktest.estimates[1:]
        atol = np.finfo(self.vamp.output_type()).eps*1000.0

        for i in range(len(pred)):
            msm = estimate_markov_model(dtrajs=self.dtrajs, lag=self.lag*(i+1), reversible=False)
            msm_esti = self.p0.T.dot(msm.P).dot(obs)
            msm_pred = self.p0.T.dot(np.linalg.matrix_power(self.msm.P, (i+1))).dot(obs)
            np.testing.assert_allclose(pred[i],  msm_pred, atol=atol)
            np.testing.assert_allclose(est[i], msm_esti, atol=atol)
            np.testing.assert_allclose(est[i], pred[i], atol=0.006)

    def test_CK_covariances_of_singular_functions(self):
        #from pyemma import config
        #config.show_progress_bars = False
        cktest = self.vamp.cktest(n_observables=2, mlags=4) # auto
        pred = cktest.predictions[1:]
        est = cktest.estimates[1:]
        error = np.max(np.abs(np.array(pred) - np.array(est))) / max(np.max(pred), np.max(est))
        assert error < 0.05

    def test_CK_covariances_against_MSM(self):
        obs = np.eye(3) # observe every state
        sta = np.eye(3) # restrict p0 to every state
        cktest = self.vamp.cktest(observables=obs, statistics=sta, mlags=4, show_progress=True)
        atol = np.finfo(self.vamp.output_type()).eps * 1000.0
        pred = cktest.predictions[1:]
        est = cktest.estimates[1:]

        for i in range(len(pred)):
            msm = estimate_markov_model(dtrajs=self.dtrajs, lag=self.lag*(i+1), reversible=False)
            msm_esti = (self.p0 * sta).T.dot(msm.P).dot(obs)
            msm_pred = (self.p0 * sta).T.dot(np.linalg.matrix_power(self.msm.P, (i+1))).dot(obs)
            np.testing.assert_allclose(np.diag(pred[i]),  np.diag(msm_pred), atol=atol)
            np.testing.assert_allclose(np.diag(est[i]), np.diag(msm_esti), atol=atol)
            np.testing.assert_allclose(np.diag(est[i]), np.diag(pred[i]), atol=0.006)

    def test_score(self):
        #TODO: complete test!
        self.vamp.score(other=self.vamp, score=1)
        self.vamp.score(other=self.vamp, score=2)
        self.vamp.score(other=self.vamp, score='E')


if __name__ == "__main__":
    unittest.main()
