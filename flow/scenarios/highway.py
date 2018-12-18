"""Contains the highway scenario class."""

from flow.scenarios.base_scenario import Scenario
from flow.core.params import InitialConfig
from flow.core.traffic_lights import TrafficLights
import numpy as np

ADDITIONAL_NET_PARAMS = {
    # length of the highway
    "length": 1000,
    # number of lanes
    "lanes": 4,
    # speed limit for all edges
    "speed_limit": 30,
    # number of edges to divide the highway into
    "num_edges": 1
}


class HighwayScenario(Scenario):
    """Highway scenario class."""

    def __init__(self,
                 name,
                 vehicles,
                 net_params,
                 initial_config=InitialConfig(),
                 traffic_lights=TrafficLights()):
        """Initialize a highway scenario.

        Requires from net_params:
        - length: length of the highway
        - lanes: number of lanes in the highway
        - speed_limit: max speed limit of the highway

        See flow/scenarios/base_scenario.py for description of params.
        """
        for p in ADDITIONAL_NET_PARAMS.keys():
            if p not in net_params.additional_params:
                raise KeyError('Network parameter "{}" not supplied'.format(p))

        self.length = net_params.additional_params["length"]
        self.lanes = net_params.additional_params["lanes"]
        self.num_edges = net_params.additional_params.get("num_edges", 1)

        super().__init__(name, vehicles, net_params, initial_config,
                         traffic_lights)

    def specify_nodes(self, net_params):
        """See parent class."""
        length = net_params.additional_params["length"]
        num_edges = net_params.additional_params.get("num_edges", 1)
        segment_lengths = np.linspace(0, length, num_edges+1)

        nodes = []
        for i in range(num_edges+1):
            nodes += [{
                "id": "edge_{}".format(i),
                "x": segment_lengths[i],
                "y": 0
            }]

        return nodes

    def specify_edges(self, net_params):
        """See parent class."""
        length = net_params.additional_params["length"]
        num_edges = net_params.additional_params.get("num_edges", 1)
        segment_length = length/float(num_edges)

        edges = []
        for i in range(num_edges):
            edges += [{
                "id": "highway_{}".format(i),
                "type": "highwayType",
                "from": "edge_{}".format(i),
                "to": "edge_{}".format(i+1),
                "length": segment_length
            }]

        return edges

    def specify_types(self, net_params):
        """See parent class."""
        lanes = net_params.additional_params["lanes"]
        speed_limit = net_params.additional_params["speed_limit"]

        types = [{
            "id": "highwayType",
            "numLanes": lanes,
            "speed": speed_limit
        }]

        return types

    def specify_routes(self, net_params):
        """See parent class."""
        num_edges = net_params.additional_params.get("num_edges", 1)
        rts = {}
        for i in range(num_edges):
            rts["highway_{}".format(i)] = ["highway_{}".format(j) for
                                           j in range(i, num_edges)]

        return rts

    def specify_edge_starts(self):
        """See parent class."""
        edgestarts = [("highway_{}".format(i), 0)
                      for i in range(self.num_edges)]
        return edgestarts

    def gen_custom_start_pos(self, initial_config, num_vehicles, **kwargs):
        """Generate a user defined set of starting positions.
        This method is just used for testing.

        Parameters
        ----------
        initial_config : InitialConfig type
            see flow/core/params.py
        num_vehicles : int
            number of vehicles to be placed on the network
        kwargs : dict
            extra components, usually defined during reset to overwrite initial
            config parameters

        Returns
        -------
        startpositions : list of tuple (float, float)
            list of start positions [(edge0, pos0), (edge1, pos1), ...]
        startlanes : list of int
            list of start lanes
        """
        return kwargs["start_positions"], kwargs["start_lanes"]
