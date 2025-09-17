import './App.css';
import BatchPanel from './components/BatchPanel/BatchPanel';
import TankContainer from './components/TankContainer/TankContainer';

function App() {
  return (
    <div className="app">
      <main>
        <section className='tankSection'>
          <TankContainer name={"Cement 1"} value="31 420"></TankContainer>
          <TankContainer name={"Cement 2"} value="32 590"></TankContainer>
          <TankContainer name={"Cement 3"} value="33 680"></TankContainer>
        </section>
        <BatchPanel></BatchPanel>
      </main>
    </div>
  );
}

export default App;
