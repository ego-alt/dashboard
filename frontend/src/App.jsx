import { useState, useEffect } from 'react';

export default function HomePage() {
  const [containers, setContainers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchContainers() {
      try {
        const response = await fetch('http://localhost:8000/containers');
        const data = await response.json();
        setContainers(data);
      } catch (error) {
        console.error('Error fetching containers:', error);
      } finally {
        setLoading(false);
      }
    }
    
    fetchContainers();
  }, []);

  async function handleContainerAction(containerId, action) {
    try {
      const response = await fetch(`http://localhost:8000/containers/${containerId}/${action}`, {
        method: 'POST',
      });
      
      if (response.ok) {
        // Refresh the container list after successful action
        const updatedResponse = await fetch('http://localhost:8000/containers');
        const updatedData = await updatedResponse.json();
        setContainers(updatedData);
      } else {
        console.error(`Failed to ${action} container`);
      }
    } catch (error) {
      console.error(`Error ${action}ing container:`, error);
    }
  }
  
  const handleStop = (containerId) => handleContainerAction(containerId, 'stop');
  const handleRestart = (containerId) => handleContainerAction(containerId, 'restart');

  if (loading) return <div className="flex justify-center items-start h-screen">Loading...</div>;

  return (
    <div className="container mx-auto py-8 px-4">
      <h1 className="text-2xl font-bold mb-6">Containers</h1>
      <div className="overflow-x-auto">
        <table className="min-w-full bg-grey border">
          <thead>
            <tr className="bg-grey-100">
              <th className="py-2 px-4 border-b text-left">Name</th>
              <th className="py-2 px-4 border-b text-left">Status</th>
              <th className="py-2 px-4 border-b text-left">CPU %</th>
              <th className="py-2 px-4 border-b text-left">Network Received (KB)</th>
              <th className="py-2 px-4 border-b text-left">Network Sent (KB)</th>
              <th className="py-2 px-4 border-b text-left">Runtime (s)</th>
              <th className="py-2 px-4 border-b text-left"></th>
              <th className="py-2 px-4 border-b text-left"></th>
            </tr>
          </thead>
          <tbody>
            {containers.map(container => (
              <tr key={container.id} className="hover:bg-gray-50 group">
                <td className="py-2 px-4 border-b group-hover:text-black">{container.name}</td>
                <td className="py-2 px-4 border-b">
                  <span className={`inline-block px-2 py-1 text-xs font-semibold rounded-full ${
                    container.status === 'running' 
                      ? 'bg-green-100 text-green-800' 
                      : 'bg-red-100 text-red-800'
                  }`}>
                    {container.status.charAt(0).toUpperCase() + container.status.slice(1)}
                  </span>
                </td>
                <td className="py-2 px-4 border-b group-hover:text-black">{container.cpu_percent}</td>
                <td className="py-2 px-4 border-b group-hover:text-black">{container.network_rx_kb}</td>
                <td className="py-2 px-4 border-b group-hover:text-black">{container.network_tx_kb}</td>
                <td className="py-2 px-4 border-b group-hover:text-black">{container.runtime_seconds}</td>
                <td className="py-2 px-4 border-b">
                  <button 
                    onClick={() => handleStop(container.id)}
                    className="w-20 px-2 py-1 text-xs text-white font-bold rounded"
                  >
                    Stop
                  </button>
                </td>
                <td className="py-2 px-4 border-b">
                  <button 
                    onClick={() => handleRestart(container.id)}
                    className="w-20 px-2 py-1 text-xs text-white font-bold rounded"
                  >
                    Restart
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}