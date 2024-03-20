use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use pyo3::exceptions::PyValueError;

use borsh::BorshDeserialize;
use namada_sdk::{
    governance::{
        storage::{
            proposal::{AddRemove, PGFAction, ProposalType, StorageProposal},
            vote::ProposalVote,
        },
        utils::{ProposalResult, TallyResult, TallyType, Vote},
    },
    proof_of_stake::types::CommissionPair,
    state::Epoch,
    address::Address,
};
use serde::Serialize;
use serde_json;
use std::collections::BTreeMap;

#[derive(Serialize)]
struct ProposalJson {
    id: u64,
    proposal_type: String,
    author: String,
    content: BTreeMap<String, String>,
    voting_start_epoch: u64,
    voting_end_epoch: u64,
    grace_epoch: u64,
    status: String,
    data: String,
}

fn format_proposal_data(proposal_type: &ProposalType) -> String {
    match proposal_type {
        ProposalType::Default(Some(hash)) => format!("Hash: {}", hash),
        ProposalType::Default(None) => String::new(),
        ProposalType::PGFSteward(addresses) => addresses
            .iter()
            .map(|add_remove| match add_remove {
                AddRemove::Add(address) => format!("Add({})", address),
                AddRemove::Remove(address) => format!("Remove({})", address),
            })
            .collect::<Vec<String>>()
            .join(", "),
        ProposalType::PGFPayment(actions) => actions
            .iter()
            .map(|action| match action {
                PGFAction::Continuous(add_remove) => match add_remove {
                    AddRemove::Add(target) => format!("Add({})", target.target()),
                    AddRemove::Remove(target) => format!("Remove({})", target.target()),
                },
                PGFAction::Retro(target) => format!("Retro({})", target.target()),
            })
            .collect::<Vec<String>>()
            .join(", "),
    }
}

#[pyfunction]
fn proposal_parse(data: &[u8], current_epoch: u64) -> PyResult<String> {
    StorageProposal::try_from_slice(data)
        .map_err(|e| PyValueError::new_err(format!("Decoding failed: {:?}", e)))
        .and_then(|proposal| {
            let proposal_json = ProposalJson {
                id: proposal.id,
                proposal_type: format!("{}", proposal.r#type),
                author: format!("{}", proposal.author),
                content: proposal.content.clone(),
                voting_start_epoch: proposal.voting_start_epoch.0,
                voting_end_epoch: proposal.voting_end_epoch.0,
                grace_epoch: proposal.grace_epoch.0,
                status: format!("{}", proposal.get_status(Epoch(current_epoch))),
                data: format_proposal_data(&proposal.r#type),
            };
            serde_json::to_string(&proposal_json)
                .map_err(|e| PyValueError::new_err(format!("Serialization failed: {:?}", e)))
        })
}

#[pyfunction]
fn votes_parse(data: &[u8]) -> PyResult<String> {
    Vec::<Vote>::try_from_slice(data)
        .map_err(|e| PyValueError::new_err(e.to_string()))
        .and_then(|votes| {
            let serializable_votes: Vec<BTreeMap<String, String>> = votes.into_iter().map(|vote| {
                let mut map = BTreeMap::new();
                map.insert("validator".to_string(), vote.validator.to_string());
                map.insert("delegator".to_string(), vote.delegator.to_string());
                map.insert("data".to_string(), match vote.data {
                    ProposalVote::Yay => "Yay",
                    ProposalVote::Nay => "Nay",
                    ProposalVote::Abstain => "Abstain",
                }.to_string());
                map
            }).collect();
            serde_json::to_string(&serializable_votes)
                .map_err(|e| PyValueError::new_err(format!("Serialization failed: {:?}", e)))
        })
}

#[pyfunction]
fn proposal_result_parse(data: &[u8]) -> PyResult<String> {
    ProposalResult::try_from_slice(data)
        .map_err(|e| PyValueError::new_err(format!("Decoding failed: {:?}", e)))
        .and_then(|result| {
            let mut map: BTreeMap<String, String> = BTreeMap::new();
            map.insert("result".to_string(), match result.result {
                TallyResult::Passed => "Passed".to_string(),
                TallyResult::Rejected => "Rejected".to_string(),
            });
            map.insert("tally_type".to_string(), match result.tally_type {
                TallyType::TwoThirds => "TwoThirds".to_string(),
                TallyType::OneHalfOverOneThird => "OneHalfOverOneThird".to_string(),
                TallyType::LessOneHalfOverOneThirdNay => "LessOneHalfOverOneThirdNay".to_string(),
            });
            map.insert("total_voting_power".to_string(), result.total_voting_power.to_string());
            map.insert("total_yay_power".to_string(), result.total_yay_power.to_string());
            map.insert("total_nay_power".to_string(), result.total_nay_power.to_string());
            map.insert("total_abstain_power".to_string(), result.total_abstain_power.to_string());

            serde_json::to_string(&map)
                .map_err(|e| PyValueError::new_err(format!("Serialization failed: {:?}", e)))
        })
}

#[pyfunction]
fn commission_pair_parse(data: &[u8]) -> PyResult<String> {
    CommissionPair::try_from_slice(data)
        .map_err(|e| PyValueError::new_err(format!("Decoding failed: {:?}", e)))
        .and_then(|commission_pair| {
            let mut map: BTreeMap<String, String> = BTreeMap::new();
            map.insert("commission_rate".to_string(), commission_pair.commission_rate.to_string());
            map.insert("max_commission_change_per_epoch".to_string(), commission_pair.max_commission_change_per_epoch.to_string());
            serde_json::to_string(&map)
                .map_err(|e| PyValueError::new_err(format!("Serialization failed: {:?}", e)))
        })
}

#[pyfunction]
fn address_parse(data: &[u8]) -> PyResult<String> {
    Address::try_from_slice(data)
        .map_err(|e| PyValueError::new_err(format!("Decoding failed: {:?}", e)))
        .map(|address| address.to_string())
}

#[pymodule]
fn rust_py(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(proposal_parse, m)?)?;
    m.add_function(wrap_pyfunction!(votes_parse, m)?)?;
    m.add_function(wrap_pyfunction!(proposal_result_parse, m)?)?;
    m.add_function(wrap_pyfunction!(commission_pair_parse, m)?)?;
    m.add_function(wrap_pyfunction!(address_parse, m)?)?;
    Ok(())
}
