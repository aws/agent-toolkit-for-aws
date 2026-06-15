import savingsPlansDataJson from '../../assets/data/savings-plans.json';
import regionsDataJson from '../../assets/data/regions.json';

function savingsPlansMap() {
  const savingsPlansDataMap = {};

  for (const savingsPlan of savingsPlansDataJson.searchResults) {
    const usageType = savingsPlan.unit.replace(/-/g, '');
    const rate = savingsPlan.rate;
    const properties = savingsPlan.properties;

    let region = null;
    for (const property of properties) {
      if (property.name === 'region') {
        region = property.value;
      }
    }
    if (!region) continue;

    const longRegionName = regionsDataJson[region];

    let regionSavingsPlans = {};
    if (longRegionName in savingsPlansDataMap) {
      regionSavingsPlans = savingsPlansDataMap[longRegionName];
    }

    regionSavingsPlans[usageType] = {
      usageType: usageType,
      rate: rate,
      region: region,
      longRegionName: longRegionName,
    };

    savingsPlansDataMap[longRegionName] = regionSavingsPlans;
  }

  return savingsPlansDataMap;
}

export default savingsPlansMap();
